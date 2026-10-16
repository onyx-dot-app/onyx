"""An attempt that ends before docfetching sets its window (for example, one
cancelled by a pause right after the scheduler created it) has no window,
checkpoint or batches. The next attempt must resume from the attempt before it,
not start from scratch and delete that attempt's leftover batches."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import connector_document_extraction
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import get_recent_completed_attempts_for_cc_pair
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_RUN_DOCFETCHING = "onyx.background.indexing.run_docfetching"
_WINDOW_START = datetime.fromtimestamp(0, tz=timezone.utc)
_WINDOW_END = datetime(2026, 1, 2, tzinfo=timezone.utc)
_FAILED_CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
_CANCELLED_CREATED = _FAILED_CREATED + timedelta(seconds=5)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _add_failed_then_unstarted_cancelled(
    db_session: Session, cc_pair_id: int, search_settings_id: int
) -> IndexAttempt:
    """A failed attempt with a window and checkpoint, then a newer attempt
    cancelled before docfetching set its window. Returns the failed one."""
    failed = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
        poll_range_start=_WINDOW_START,
        poll_range_end=_WINDOW_END,
        checkpoint_pointer=f"checkpoint_test_{uuid4().hex[:8]}.json",
        completed_batches=2,
        total_batches=None,
        time_created=_FAILED_CREATED,
    )
    cancelled = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=IndexingStatus.CANCELED,
        time_created=_CANCELLED_CREATED,
    )
    db_session.add_all([failed, cancelled])
    db_session.commit()
    return failed


def test_recent_completed_attempts_skip_unstarted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    search_settings_id = get_current_search_settings(db_session).id
    failed = _add_failed_then_unstarted_cancelled(
        db_session, cc_pair.id, search_settings_id
    )

    results = get_recent_completed_attempts_for_cc_pair(
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        limit=10,
        db_session=db_session,
    )

    assert [a.id for a in results] == [failed.id]


@patch(f"{_RUN_DOCFETCHING}.reissue_old_batches", return_value=(3, 2))
@patch(f"{_RUN_DOCFETCHING}.get_document_batch_storage")
@patch(f"{_RUN_DOCFETCHING}.MemoryTracer")
@patch(f"{_RUN_DOCFETCHING}._get_connector_runner")
@patch(f"{_RUN_DOCFETCHING}.strip_null_characters", side_effect=lambda batch: batch)
@patch(f"{_RUN_DOCFETCHING}.get_last_successful_attempt_poll_range_end")
@patch(f"{_RUN_DOCFETCHING}.save_checkpoint")
@patch("onyx.background.indexing.checkpointing_utils.load_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_redis_client")
@patch(f"{_RUN_DOCFETCHING}.ensure_source_node_exists")
@patch(f"{_RUN_DOCFETCHING}.get_source_node_id_from_cache")
@patch(f"{_RUN_DOCFETCHING}.get_node_id_from_raw_id")
@patch(f"{_RUN_DOCFETCHING}.cache_hierarchy_nodes_batch")
def test_docfetching_reissues_batches_past_unstarted_attempt(
    mock_cache_hierarchy_nodes_batch: MagicMock,  # noqa: ARG001
    mock_get_node_id_from_raw_id: MagicMock,
    mock_get_source_node_id_from_cache: MagicMock,
    mock_ensure_source_node_exists: MagicMock,
    mock_get_redis_client: MagicMock,
    mock_load_checkpoint: MagicMock,
    mock_save_checkpoint: MagicMock,  # noqa: ARG001
    mock_get_last_successful_attempt_poll_range_end: MagicMock,
    mock_strip_null_characters: MagicMock,  # noqa: ARG001
    mock_get_connector_runner: MagicMock,
    mock_memory_tracer_class: MagicMock,  # noqa: ARG001
    mock_get_batch_storage: MagicMock,
    mock_reissue_old_batches: MagicMock,
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    """The CI failure of test_mock_connector_checkpoint_recovery: the attempt
    after the cancelled one took a fresh window, found no valid checkpoint and
    deleted the failed attempt's leftover batches."""
    search_settings_id = get_current_search_settings(db_session).id
    _add_failed_then_unstarted_cancelled(db_session, cc_pair.id, search_settings_id)
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"test_celery_task_{uuid4().hex[:8]}",
        time_created=_CANCELLED_CREATED + timedelta(seconds=5),
    )
    db_session.add(attempt)
    db_session.commit()

    batch_storage = MagicMock()
    mock_get_batch_storage.return_value = batch_storage
    mock_get_redis_client.return_value = MagicMock()
    mock_ensure_source_node_exists.return_value = 1
    mock_get_source_node_id_from_cache.return_value = 1
    mock_get_node_id_from_raw_id.return_value = (None, False)
    mock_get_last_successful_attempt_poll_range_end.return_value = 0
    mock_load_checkpoint.return_value = ConnectorCheckpoint(has_more=True)

    connector_runner = MagicMock()
    connector_runner.connector = MagicMock(spec=CheckpointedConnector)
    connector_runner.connector.build_dummy_checkpoint.return_value = (
        ConnectorCheckpoint(has_more=True)
    )
    connector_runner.run.return_value = iter(
        [([], None, None, ConnectorCheckpoint(has_more=False))]
    )
    mock_get_connector_runner.return_value = connector_runner

    connector_document_extraction(
        app=MagicMock(),
        index_attempt_id=attempt.id,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        callback=None,
    )

    db_session.expire_all()
    refreshed = db_session.get(IndexAttempt, attempt.id)
    assert refreshed is not None
    assert refreshed.poll_range_end == _WINDOW_END
    mock_reissue_old_batches.assert_called_once()
    batch_storage.cleanup_all_batches.assert_not_called()
