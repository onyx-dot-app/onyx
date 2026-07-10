"""External dependency unit tests for the doc_created_at backfill (acquisition half).

Validates that the pruning-side collection of a source creation time works:
1. extract_ids_from_runnable_connector captures doc_created_at from slim docs.
2. backfill_docs_created_at__no_commit persists it and bumps last_modified so the
   metadata sync task will propagate it.
3. The bump only happens when the value actually changes (no re-sync churn).

Uses a mock SlimConnector plus a real PostgreSQL database.
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.db.document import backfill_docs_created_at__no_commit
from onyx.db.models import Document as DbDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.kg.models import KGStage

_CREATED_AT = datetime(2021, 6, 1, tzinfo=timezone.utc)


class _MockSlimConnector(SlimConnector):
    """Yields a single batch of the given slim docs."""

    def __init__(self, docs: list[SlimDocument]) -> None:
        self._docs = docs

    def load_credentials(
        self,
        credentials: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        return None

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        batch: list[SlimDocument | HierarchyNode] = list(self._docs)
        yield batch


def test_extraction_captures_doc_created_at() -> None:
    docs = [
        SlimDocument(id="doc-a", doc_created_at=_CREATED_AT),
        SlimDocument(id="doc-b"),  # no creation time supplied
    ]
    result = extract_ids_from_runnable_connector(
        _MockSlimConnector(docs), callback=None
    )

    # both docs are enumerated for pruning...
    assert result.raw_id_to_parent.keys() == {"doc-a", "doc-b"}
    # ...but only the one carrying a value contributes a created_at
    assert result.id_to_created_at == {"doc-a": _CREATED_AT}


def test_backfill_sets_created_at_and_bumps_last_modified(db_session: Session) -> None:
    doc_id = f"created-at-backfill-{uuid4().hex[:8]}"
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=2,
            doc_created_at=None,
            last_modified=old_modified,
        )
    )
    db_session.commit()
    try:
        backfill_docs_created_at__no_commit({doc_id: _CREATED_AT}, db_session)
        db_session.commit()

        db_session.expire_all()
        row = db_session.get(DbDocument, doc_id)
        assert row is not None
        assert row.doc_created_at == _CREATED_AT
        # dirtied so the metadata sync task (last_modified > last_synced) picks it up
        assert row.last_modified is not None and row.last_modified > old_modified
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()


def test_backfill_is_noop_when_value_unchanged(db_session: Session) -> None:
    doc_id = f"created-at-backfill-{uuid4().hex[:8]}"
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=2,
            doc_created_at=_CREATED_AT,  # already set to the incoming value
        )
    )
    db_session.commit()
    try:
        db_session.expire_all()
        before = db_session.get(DbDocument, doc_id)
        assert before is not None
        last_modified_before = before.last_modified

        backfill_docs_created_at__no_commit({doc_id: _CREATED_AT}, db_session)
        db_session.commit()

        db_session.expire_all()
        after = db_session.get(DbDocument, doc_id)
        assert after is not None
        # value already matched → row not touched, so no needless re-sync
        assert after.doc_created_at == _CREATED_AT
        assert after.last_modified == last_modified_before
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()


def test_backfill_skips_doc_without_chunk_count(db_session: Session) -> None:
    # An unknown chunk count makes the metadata-sync update a no-op, so the
    # backfill must NOT persist created_at (which would falsely mark it synced);
    # it's left for a later sweep once indexing sets the count.
    doc_id = f"created-at-backfill-{uuid4().hex[:8]}"
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=None,
            doc_created_at=None,
            last_modified=old_modified,
        )
    )
    db_session.commit()
    try:
        backfill_docs_created_at__no_commit({doc_id: _CREATED_AT}, db_session)
        db_session.commit()

        db_session.expire_all()
        row = db_session.get(DbDocument, doc_id)
        assert row is not None
        # not persisted, not dirtied → retried on a later sweep
        assert row.doc_created_at is None
        assert row.last_modified == old_modified
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()
