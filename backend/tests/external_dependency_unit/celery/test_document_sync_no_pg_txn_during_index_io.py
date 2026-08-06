"""
Regression coverage for document_index_metadata_sync_task holding a Postgres
transaction across the document-index (Vespa/OpenSearch) HTTP round-trip.

Under bulk-deletion fan-out, every docprocessing-sync worker slot used to pin a
DB connection in state idle-in-transaction for the duration of the index call
(up to RetryDocumentIndex.STOP_AFTER seconds of tenacity retries). Those
transactions blocked `UPDATE document SET last_synced` writers cluster-wide.
The task is now split into three phases: read DB state and close the session,
do index I/O with no connection held, then reopen a fresh session to mark the
document synced.

Uses real PostgreSQL for Document rows and search settings. Only
RetryDocumentIndex.update is mocked (no index network I/O), so index-client
construction runs for real against the detached-from-session SearchSettings —
guarding the phase boundary itself.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.background.celery.tasks.vespa import tasks as vespa_tasks
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.models import Document as DbDocument
from onyx.document_index.interfaces_new import SecondaryIndexDocumentMissingError
from onyx.kg.models import KGStage
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)

_LAST_MODIFIED = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def stale_document(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> Generator[str, None, None]:
    """A document row that needs syncing (last_synced is NULL)."""
    doc_id = f"doc-sync-pg-txn-{uuid4().hex[:8]}"
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=1,
            last_modified=_LAST_MODIFIED,
            last_synced=None,
        )
    )
    db_session.commit()
    try:
        yield doc_id
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()


def _run_task(doc_id: str, index_update_side_effect: object = None) -> bool:
    """Run the sync task with RetryDocumentIndex.update patched.

    Index clients are still built by the real factory from search settings that
    are detached from their (closed) phase-1 session.
    """
    with patch.object(
        RetryDocumentIndex, "update", side_effect=index_update_side_effect
    ):
        result: bool = vespa_tasks.document_index_metadata_sync_task.apply(
            args=(doc_id,), kwargs={"tenant_id": TEST_TENANT_ID}
        ).get()
        return result


def test_no_db_connection_held_during_index_io(
    stale_document: str, db_session: Session
) -> None:
    pool = cast(QueuePool, SqlEngine.get_engine().pool)
    checked_out_during_update: list[int] = []
    baseline = pool.checkedout()

    def _record_pool_state(_update_requests: object) -> None:
        checked_out_during_update.append(pool.checkedout() - baseline)

    result = _run_task(stale_document, index_update_side_effect=_record_pool_state)

    assert result is True
    # the index update ran (once per configured index)...
    assert len(checked_out_during_update) >= 1
    # ...with no DB connection checked out by the task at any of those moments
    assert all(count == 0 for count in checked_out_during_update)

    db_session.expire_all()
    row = db_session.get(DbDocument, stale_document)
    assert row is not None
    # last_synced carries the phase-1 last_modified watermark
    assert row.last_synced == _LAST_MODIFIED
    assert row.secondary_only_sync_pending is False


def test_concurrent_modification_during_index_io_stays_stale(
    stale_document: str, db_session: Session
) -> None:
    """A metadata change (e.g. ACL update) landing while the index write is in
    flight must leave the doc stale so the newer state re-syncs — the sync
    marker must not mask it with a later last_synced timestamp."""
    bumped_last_modified = datetime.now(timezone.utc)

    def _bump_last_modified(_update_requests: object) -> None:
        with get_session_with_current_tenant() as concurrent_session:
            concurrent_session.query(DbDocument).filter(
                DbDocument.id == stale_document
            ).update({DbDocument.last_modified: bumped_last_modified})
            concurrent_session.commit()

    result = _run_task(stale_document, index_update_side_effect=_bump_last_modified)

    assert result is True
    db_session.expire_all()
    row = db_session.get(DbDocument, stale_document)
    assert row is not None
    # synced up to the phase-1 watermark only...
    assert row.last_synced == _LAST_MODIFIED
    # ...so the concurrent bump keeps the doc eligible for another sync pass
    assert row.last_modified is not None
    assert row.last_synced is not None
    assert row.last_modified > row.last_synced


def test_port_missing_doc_still_marked_synced_in_fresh_session(
    stale_document: str, db_session: Session
) -> None:
    """SecondaryIndexDocumentMissingError defers the index write; a doc with no
    indexable cc_pair must still be marked synced (phase 3, fresh session) so
    the needs-sync flag can't wedge an index swap."""
    result = _run_task(
        stale_document,
        index_update_side_effect=SecondaryIndexDocumentMissingError([stale_document]),
    )

    assert result is True
    db_session.expire_all()
    row = db_session.get(DbDocument, stale_document)
    assert row is not None
    assert row.last_synced == _LAST_MODIFIED
    assert row.secondary_only_sync_pending is False
