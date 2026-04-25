# knowledge_layer/background/ingest_worker.py
from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path

from celery import shared_task
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session
from knowledge_layer.db.models import (
    CrossRef,
    IngestRun,
    IngestStatus,
    TopicExt,
    WikiPage,
    WikiPageVersion,
)
from knowledge_layer.connectors.filesystem import _SUPPORTED_EXTENSIONS
from knowledge_layer.providers.base import LLMProvider, TopicSummary, WikiPageDraft
from knowledge_layer.providers.claude import ClaudeProvider


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _should_skip(content_hash: str, last_run: IngestRun | None) -> bool:
    if last_run is None:
        return False
    return last_run.status == IngestStatus.SUCCESS and last_run.source_content_hash == content_hash


def _get_existing_pages(db: Session, topic_id: int) -> list[WikiPageDraft]:
    pages = db.query(WikiPage).filter(
        WikiPage.topic_id == topic_id,
        WikiPage.is_index_page.is_(False),
    ).all()
    return [WikiPageDraft(slug=p.slug, title=p.title, content=p.content) for p in pages]


def _build_index_content(topic_name: str, pages: list) -> str:
    lines = [f"# {topic_name} Index"]
    for page in sorted(pages, key=lambda p: p.slug):
        lines.append(f"- [{page.title}]({page.slug})")
    return "\n".join(lines)


def _regenerate_index_page(db: Session, topic: TopicExt, pages: list) -> None:
    content = _build_index_content(topic.name, pages)
    content_hash = _sha256(content)

    existing = (
        db.query(WikiPage)
        .filter(WikiPage.topic_id == topic.id, WikiPage.slug == "index")
        .first()
    )

    if existing is None:
        page = WikiPage(
            topic_id=topic.id,
            slug="index",
            title=f"{topic.name} Index",
            content=content,
            content_hash=content_hash,
            is_index_page=True,
        )
        db.add(page)
        db.flush()
    else:
        if existing.content_hash != content_hash:
            existing.content = content
            existing.content_hash = content_hash


@dataclass
class _ResolvedRef:
    from_page_id: int
    to_slug: str
    link_type: str
    to_topic_id: int | None  # None = same topic or unresolvable


def _resolve_cross_refs(
    db: Session,
    current_topic_id: int,
    proposals: list,  # list[CrossRefProposal]
    all_pages: list,  # list[WikiPage] — all non-index pages in current topic
) -> list[_ResolvedRef]:
    """Resolve CrossRefProposals to _ResolvedRef with to_topic_id populated."""
    slug_to_page = {p.slug: p for p in all_pages}
    resolved = []

    for prop in proposals:
        from_page = slug_to_page.get(prop.from_slug)
        if from_page is None:
            continue  # from_slug not in current topic — skip

        to_topic_id: int | None = None

        if prop.to_slug not in slug_to_page:
            # Not in current topic — try to resolve via to_topic hint
            if prop.to_topic:
                target_topic = (
                    db.query(TopicExt)
                    .filter(TopicExt.name == prop.to_topic)
                    .first()
                )
                if target_topic and target_topic.id != current_topic_id:
                    target_page = (
                        db.query(WikiPage)
                        .filter(
                            WikiPage.topic_id == target_topic.id,
                            WikiPage.slug == prop.to_slug,
                            WikiPage.is_index_page.is_(False),
                        )
                        .first()
                    )
                    if target_page:
                        to_topic_id = target_topic.id

        resolved.append(_ResolvedRef(
            from_page_id=from_page.id,
            to_slug=prop.to_slug,
            link_type=prop.link_type,
            to_topic_id=to_topic_id,
        ))

    return resolved


def _upsert_wiki_page(db: Session, topic_id: int, draft: WikiPageDraft) -> WikiPage:
    content_hash = _sha256(draft.content)
    page = db.query(WikiPage).filter(
        WikiPage.topic_id == topic_id,
        WikiPage.slug == draft.slug,
    ).first()

    if page is None:
        page = WikiPage(
            topic_id=topic_id,
            slug=draft.slug,
            title=draft.title,
            content=draft.content,
            content_hash=content_hash,
        )
        db.add(page)
        db.flush()
        version_num = 1
    else:
        page.title = draft.title
        page.content = draft.content
        page.content_hash = content_hash
        version_num = (
            db.query(WikiPageVersion)
            .filter(WikiPageVersion.page_id == page.id)
            .count()
        ) + 1

    # TODO(phase-2): add retention policy — unbounded version rows accumulate indefinitely.
    db.add(WikiPageVersion(
        page_id=page.id,
        version_num=version_num,
        content=draft.content,
        content_hash=content_hash,
    ))
    return page


def ingest_file(
    db: Session,
    topic: TopicExt,
    file_path: str,
    file_content: str,
    provider: LLMProvider,
) -> None:
    content_hash = _sha256(file_content)
    doc_id = f"wiki_raw_fs::{file_path}"

    last_run = (
        db.query(IngestRun)
        .filter(IngestRun.topic_id == topic.id, IngestRun.source_doc_id == doc_id)
        .order_by(IngestRun.created_at.desc())
        .first()
    )

    if _should_skip(content_hash, last_run):
        return

    run = IngestRun(
        topic_id=topic.id,
        source_doc_id=doc_id,
        source_content_hash=content_hash,
        status=IngestStatus.RUNNING,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(run)
    db.commit()

    try:
        # Build sibling context for cross-topic cross-ref hints
        sibling_topics = [
            TopicSummary(
                name=t.name,
                page_slugs=[
                    p.slug for p in db.query(WikiPage).filter(
                        WikiPage.topic_id == t.id,
                        WikiPage.is_index_page.is_(False),
                    ).all()
                ],
            )
            for t in db.query(TopicExt).filter(TopicExt.id != topic.id).all()
        ]

        existing = _get_existing_pages(db, topic.id)
        result = provider.ingest_call(
            raw_content=file_content,
            existing_pages=existing,
            topic_name=topic.name,
            sibling_topics=sibling_topics,
        )

        for draft in result.wiki_pages:
            _upsert_wiki_page(db, topic.id, draft)

        # Get all non-index pages after upserts for resolver + index generation
        all_current_pages = db.query(WikiPage).filter(
            WikiPage.topic_id == topic.id,
            WikiPage.is_index_page.is_(False),
        ).all()

        # Idempotent cross-ref upsert: delete old refs from this topic, reinsert resolved
        from_page_ids = {p.id for p in all_current_pages}
        if from_page_ids:
            db.query(CrossRef).filter(
                CrossRef.from_page_id.in_(from_page_ids)
            ).delete(synchronize_session=False)

        resolved_refs = _resolve_cross_refs(
            db=db,
            current_topic_id=topic.id,
            proposals=result.cross_refs,
            all_pages=all_current_pages,
        )
        for ref in resolved_refs:
            db.add(CrossRef(
                from_page_id=ref.from_page_id,
                to_slug=ref.to_slug,
                link_type=ref.link_type,
                to_topic_id=ref.to_topic_id,
            ))

        _regenerate_index_page(db, topic, all_current_pages)

        run.status = IngestStatus.SUCCESS
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()

    except Exception as exc:
        run.status = IngestStatus.FAILED
        run.error_msg = str(exc)
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        raise


@shared_task(name="knowledge_layer.ingest_worker")
def run_ingest_worker() -> None:
    """Periodic Celery task: scan all topics and ingest changed raw files."""
    provider = ClaudeProvider()

    with get_session() as db:
        topics = db.query(TopicExt).all()

        for topic in topics:
            root = Path(topic.watch_path)
            if not root.exists():
                continue
            root_resolved = root.resolve()

            for entry in sorted(root.rglob("*")):
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                    continue
                try:
                    entry.resolve().relative_to(root_resolved)
                except ValueError:
                    continue  # symlink escape — skip

                try:
                    content = entry.read_text(encoding="utf-8", errors="replace")
                    ingest_file(
                        db=db,
                        topic=topic,
                        file_path=str(entry.resolve()),
                        file_content=content,
                        provider=provider,
                    )
                except Exception:
                    pass  # error recorded in IngestRun; continue remaining files
