# knowledge_layer/background/ingest_worker.py
from __future__ import annotations

import datetime
import hashlib
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
from knowledge_layer.providers.base import LLMProvider, WikiPageDraft
from knowledge_layer.providers.claude import ClaudeProvider

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".rst"}


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _should_skip(content_hash: str, last_run: IngestRun | None) -> bool:
    if last_run is None:
        return False
    return last_run.status == IngestStatus.SUCCESS and last_run.source_content_hash == content_hash


def _get_existing_pages(db: Session, topic_id: int) -> list[WikiPageDraft]:
    pages = db.query(WikiPage).filter(WikiPage.topic_id == topic_id).all()
    return [WikiPageDraft(slug=p.slug, title=p.title, content=p.content) for p in pages]


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
        started_at=datetime.datetime.utcnow(),
    )
    db.add(run)
    db.commit()

    try:
        existing = _get_existing_pages(db, topic.id)
        result = provider.ingest_call(
            raw_content=file_content,
            existing_pages=existing,
            topic_name=topic.name,
        )

        for draft in result.wiki_pages:
            _upsert_wiki_page(db, topic.id, draft)

        for ref in result.cross_refs:
            from_page = db.query(WikiPage).filter(
                WikiPage.topic_id == topic.id,
                WikiPage.slug == ref.from_slug,
            ).first()
            if from_page:
                db.add(CrossRef(
                    from_page_id=from_page.id,
                    to_slug=ref.to_slug,
                    link_type=ref.link_type,
                ))

        run.status = IngestStatus.SUCCESS
        run.completed_at = datetime.datetime.utcnow()
        db.commit()

    except Exception as exc:
        run.status = IngestStatus.FAILED
        run.error_msg = str(exc)
        run.completed_at = datetime.datetime.utcnow()
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

            for entry in sorted(root.rglob("*")):
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                    continue

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
