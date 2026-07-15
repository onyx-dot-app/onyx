"""
Tests for batched orphan-tag cleanup.

Orphan tags (tags with no Document__Tag link) must be deleted in bounded
server-side batches rather than one unbounded IN-list DELETE.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.db.models import Document__Tag
from onyx.db.models import Tag
from onyx.db.tag import _delete_orphan_tags_batch
from onyx.db.tag import delete_orphan_tags__no_commit
from onyx.db.tag import delete_orphan_tags_batched


def _seed_orphan_tags(db_session: Session, count: int) -> list[int]:
    """Create tags with no Document__Tag links. Returns their ids."""
    run_id = uuid4().hex[:8]
    tags = [
        Tag(
            tag_key=f"orphan_key_{run_id}_{i}",
            tag_value=f"orphan_value_{run_id}_{i}",
            source=DocumentSource.FILE,
            is_list=False,
        )
        for i in range(count)
    ]
    db_session.add_all(tags)
    db_session.commit()
    return [tag.id for tag in tags]


def _seed_linked_tags(db_session: Session, count: int) -> list[int]:
    """Create tags each linked to a document. Returns the tag ids."""
    run_id = uuid4().hex[:8]
    document = Document(
        id=f"orphan_tag_test_doc_{run_id}",
        semantic_id=f"semantic_orphan_tag_test_doc_{run_id}",
        boost=0,
        hidden=False,
        from_ingestion_api=False,
    )
    db_session.add(document)

    tags = [
        Tag(
            tag_key=f"linked_key_{run_id}_{i}",
            tag_value=f"linked_value_{run_id}_{i}",
            source=DocumentSource.FILE,
            is_list=False,
        )
        for i in range(count)
    ]
    db_session.add_all(tags)
    db_session.flush()

    db_session.add_all(
        Document__Tag(document_id=document.id, tag_id=tag.id) for tag in tags
    )
    db_session.commit()
    return [tag.id for tag in tags]


def _fetch_existing_tag_ids(tag_ids: list[int]) -> set[int]:
    with get_session_with_current_tenant() as session:
        return set(
            session.execute(select(Tag.id).where(Tag.id.in_(tag_ids))).scalars().all()
        )


class TestOrphanTagCleanup:
    def test_batched_drain_deletes_all_orphans_across_batches(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        # Drain any orphans left over from other tests so counts are exact.
        delete_orphan_tags_batched(db_session)

        orphan_ids = _seed_orphan_tags(db_session, 25)
        linked_ids = _seed_linked_tags(db_session, 3)

        with patch(
            "onyx.db.tag._delete_orphan_tags_batch",
            wraps=_delete_orphan_tags_batch,
        ) as batch_spy:
            total_deleted = delete_orphan_tags_batched(db_session, batch_size=10)

        assert total_deleted == 25
        # 10 + 10 + 5 + terminating 0-row batch
        assert batch_spy.call_count == 4

        assert _fetch_existing_tag_ids(orphan_ids) == set()
        assert _fetch_existing_tag_ids(linked_ids) == set(linked_ids)

    def test_batched_drain_no_orphans_is_noop(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        delete_orphan_tags_batched(db_session)

        linked_ids = _seed_linked_tags(db_session, 2)

        with patch(
            "onyx.db.tag._delete_orphan_tags_batch",
            wraps=_delete_orphan_tags_batch,
        ) as batch_spy:
            total_deleted = delete_orphan_tags_batched(db_session, batch_size=10)

        assert total_deleted == 0
        assert batch_spy.call_count == 1

        assert _fetch_existing_tag_ids(linked_ids) == set(linked_ids)

    def test_no_commit_variant_is_bounded_and_does_not_commit(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        delete_orphan_tags_batched(db_session)

        orphan_ids = _seed_orphan_tags(db_session, 25)

        num_deleted = delete_orphan_tags__no_commit(db_session, batch_size=10)
        assert num_deleted == 10

        # Uncommitted: rolling back must restore every seeded orphan.
        db_session.rollback()
        assert _fetch_existing_tag_ids(orphan_ids) == set(orphan_ids)

        # Cleanup so later tests start from a clean slate.
        delete_orphan_tags_batched(db_session)
        assert _fetch_existing_tag_ids(orphan_ids) == set()
