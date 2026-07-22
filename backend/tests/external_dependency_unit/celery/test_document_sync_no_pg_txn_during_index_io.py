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

Uses real PostgreSQL for Document rows and search settings; the document index
is mocked so the test can observe pool state at the exact moment of index I/O.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from onyx.background.celery.tasks.vespa import tasks as vespa_tasks
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import Document as DbDocument
from onyx.document_index.interfaces_new import SecondaryIndexDocumentMissingError
from onyx.kg.models import KGStage
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)


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
            last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
            last_synced=None,
        )
    )
    db_session.commit()
    try:
        yield doc_id
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()


def _run_task_with_mock_index(
    doc_id: str, index_update_side_effect: Exception | None = None
) -> tuple[bool, list[int]]:
    """Run the sync task against a mocked document index.

    Returns the task's return value and the engine pool's checked-out
    connection counts (relative to the pre-task baseline) sampled inside each
    index update() call.
    """
    pool = cast(QueuePool, SqlEngine.get_engine().pool)
    checked_out_during_update: list[int] = []

    baseline = pool.checkedout()

    fake_index = MagicMock()

    def _record_pool_state(_update_requests: object) -> None:
        checked_out_during_update.append(pool.checkedout() - baseline)
        if index_update_side_effect is not None:
            raise index_update_side_effect

    fake_index.update.side_effect = _record_pool_state

    with patch.object(
        vespa_tasks, "get_all_document_indices", return_value=[fake_index]
    ):
        result = vespa_tasks.document_index_metadata_sync_task.apply(
            args=(doc_id,), kwargs={"tenant_id": TEST_TENANT_ID}
        ).get()

    return result, checked_out_during_update


def test_no_db_connection_held_during_index_io(
    stale_document: str, db_session: Session
) -> None:
    result, checked_out_during_update = _run_task_with_mock_index(stale_document)

    assert result is True
    # the index update must have run exactly once...
    assert len(checked_out_during_update) == 1
    # ...with no DB connection checked out by the task at that moment
    assert checked_out_during_update == [0]

    db_session.expire_all()
    row = db_session.get(DbDocument, stale_document)
    assert row is not None
    assert row.last_synced is not None
    assert row.secondary_only_sync_pending is False


def test_port_missing_doc_still_marked_synced_in_fresh_session(
    stale_document: str, db_session: Session
) -> None:
    """SecondaryIndexDocumentMissingError defers the index write; a doc with no
    indexable cc_pair must still be marked synced (phase 3, fresh session) so
    the needs-sync flag can't wedge an index swap."""
    result, checked_out_during_update = _run_task_with_mock_index(
        stale_document,
        index_update_side_effect=SecondaryIndexDocumentMissingError([stale_document]),
    )

    assert result is True
    assert checked_out_during_update == [0]

    db_session.expire_all()
    row = db_session.get(DbDocument, stale_document)
    assert row is not None
    assert row.last_synced is not None
    assert row.secondary_only_sync_pending is False
