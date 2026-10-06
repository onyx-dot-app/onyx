"""A backfill attempt runs a fixed window, optionally with an override config,
and stays out of the pair's incremental cursor, checkpoint reuse, status and
first-attempt hold. It still fences other attempts like a full run."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docfetching.task_creation_utils import (
    try_creating_backfill_attempt,
)
from onyx.background.celery.tasks.docprocessing.tasks import check_indexing_completion
from onyx.background.indexing.models import BackfillSpec
from onyx.background.indexing.run_docfetching import (
    _get_connector_runner,
    connector_document_extraction,
)
from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import source_supports_windowed_runs
from onyx.connectors.models import ConnectorCheckpoint, Document, TextSection
from onyx.db.connector_credential_pair import (
    get_last_successful_attempt_poll_range_end,
    resync_cc_pair,
)
from onyx.db.constants import CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX
from onyx.db.enums import ConnectorCredentialPairStatus, IndexingStatus
from onyx.db.index_attempt import (
    cc_pair_has_dispatched_index_attempts,
    get_last_attempt_for_cc_pair,
    get_recent_attempts_for_cc_pair,
)
from onyx.db.indexing_coordination import CoordinationStatus, IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, SearchSettings
from onyx.db.search_settings import get_current_search_settings
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_CONFIG: dict[str, Any] = {"channels": ["general", "random"]}
_OVERRIDE_CONFIG: dict[str, Any] = {"channels": ["random"]}
_RUN_DOCFETCHING = "onyx.background.indexing.run_docfetching"
_TASK_CREATION = "onyx.background.celery.tasks.docfetching.task_creation_utils"

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)
_NORMAL_END = datetime(2026, 3, 1, tzinfo=timezone.utc)
_BACKFILL_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_BACKFILL_END = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    pair.connector.connector_specific_config = _CONFIG
    db_session.commit()
    try:
        yield pair
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def search_settings(db_session: Session) -> SearchSettings:
    return get_current_search_settings(db_session)


def _backfill_spec(override: dict[str, Any] | None) -> BackfillSpec:
    return BackfillSpec(
        window_start=_BACKFILL_START,
        window_end=_BACKFILL_END,
        connector_config_override=override,
    )


def _create_backfill(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    override: dict[str, Any] | None = _OVERRIDE_CONFIG,
) -> IndexAttempt:
    attempt_id = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        celery_task_id=f"test_backfill_{uuid4().hex[:8]}",
        backfill=_backfill_spec(override),
    )
    assert attempt_id is not None
    attempt = db_session.get(IndexAttempt, attempt_id)
    assert attempt is not None
    return attempt


def _add_normal_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    status: IndexingStatus,
    poll_range_end: datetime,
    poll_range_start: datetime = _EPOCH,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=status,
        poll_range_start=poll_range_start,
        poll_range_end=poll_range_end,
        checkpoint_pointer=f"checkpoint_test_{uuid4().hex[:8]}.json",
        connector_config_hash=compute_connector_config_hash(_CONFIG),
        celery_task_id=f"test_normal_{uuid4().hex[:8]}",
        time_started=datetime.now(tz=timezone.utc),
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _finish(db_session: Session, attempt: IndexAttempt, status: IndexingStatus) -> None:
    attempt.status = status
    attempt.time_started = datetime.now(tz=timezone.utc)
    db_session.commit()


def test_backfill_creation_stamps_window_and_override_hash(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    with_override = _create_backfill(db_session, cc_pair.id, search_settings.id)
    assert with_override.is_backfill
    assert with_override.from_beginning is False
    assert with_override.poll_range_start == _BACKFILL_START
    assert with_override.poll_range_end == _BACKFILL_END
    assert with_override.connector_config_override == _OVERRIDE_CONFIG
    assert with_override.connector_config_hash == compute_connector_config_hash(
        _OVERRIDE_CONFIG
    )
    _finish(db_session, with_override, IndexingStatus.SUCCESS)

    saved_config = _create_backfill(
        db_session, cc_pair.id, search_settings.id, override=None
    )
    assert saved_config.connector_config_override is None
    assert saved_config.connector_config_hash == compute_connector_config_hash(_CONFIG)


class _NoOffset(tzinfo):
    """Set but naive: Python treats a None offset as no timezone."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:  # noqa: ARG002
        return None


def test_backfill_window_must_be_ordered_and_aware() -> None:
    with pytest.raises(ValueError):
        BackfillSpec(window_start=_BACKFILL_END, window_end=_BACKFILL_START)
    with pytest.raises(ValueError):
        BackfillSpec(
            window_start=_BACKFILL_START.replace(tzinfo=None),
            window_end=_BACKFILL_END,
        )
    with pytest.raises(ValueError):
        BackfillSpec(
            window_start=_BACKFILL_START.replace(tzinfo=_NoOffset()),
            window_end=_BACKFILL_END,
        )


def test_backfill_stays_out_of_cursor_status_and_hold(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    _finish(db_session, backfill, IndexingStatus.SUCCESS)

    # only a backfill exists: it neither unlocks the first-attempt hold nor
    # gives the pair a cursor or a last successful index time
    assert not cc_pair_has_dispatched_index_attempts(db_session, cc_pair.id)
    assert (
        get_last_successful_attempt_poll_range_end(
            cc_pair_id=cc_pair.id,
            earliest_index=0,
            search_settings=search_settings,
            db_session=db_session,
        )
        == 0
    )
    resync_cc_pair(cc_pair, search_settings.id, db_session)
    assert cc_pair.last_successful_index_time is None

    normal = _add_normal_attempt(
        db_session,
        cc_pair.id,
        search_settings.id,
        IndexingStatus.SUCCESS,
        poll_range_end=_NORMAL_END,
    )
    # a later backfill that ends after the normal cursor does not move it
    later_backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    _finish(db_session, later_backfill, IndexingStatus.FAILED)

    assert (
        get_last_successful_attempt_poll_range_end(
            cc_pair_id=cc_pair.id,
            earliest_index=0,
            search_settings=search_settings,
            db_session=db_session,
        )
        == _NORMAL_END.timestamp()
    )
    last_attempt = get_last_attempt_for_cc_pair(
        cc_pair.id, search_settings.id, db_session
    )
    assert last_attempt is not None and last_attempt.id == normal.id
    # repeated-error detection ignores the failed backfill; deletion sees it
    assert [
        a.id
        for a in get_recent_attempts_for_cc_pair(
            cc_pair.id, search_settings.id, limit=1, db_session=db_session
        )
    ] == [normal.id]
    assert [
        a.id
        for a in get_recent_attempts_for_cc_pair(
            cc_pair.id,
            search_settings.id,
            limit=1,
            db_session=db_session,
            ignore_backfill=False,
        )
    ] == [later_backfill.id]
    assert cc_pair_has_dispatched_index_attempts(db_session, cc_pair.id)


def test_backfill_and_normal_attempts_fence_each_other(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    assert (
        IndexingCoordination.try_create_index_attempt(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            celery_task_id="test_blocked_normal",
        )
        is None
    )
    _finish(db_session, backfill, IndexingStatus.SUCCESS)

    normal_id = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        celery_task_id="test_normal",
    )
    assert normal_id is not None
    assert (
        IndexingCoordination.try_create_index_attempt(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            celery_task_id="test_blocked_backfill",
            backfill=_backfill_spec(_OVERRIDE_CONFIG),
        )
        is None
    )


@pytest.mark.parametrize(
    "pair_status,held,expect_created",
    [
        (ConnectorCredentialPairStatus.ACTIVE, False, True),
        (ConnectorCredentialPairStatus.ACTIVE, True, False),
        (ConnectorCredentialPairStatus.PAUSED, False, False),
        (ConnectorCredentialPairStatus.DELETING, False, False),
    ],
)
def test_try_creating_backfill_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    pair_status: ConnectorCredentialPairStatus,
    held: bool,
    expect_created: bool,
) -> None:
    cc_pair.status = pair_status
    db_session.commit()
    celery_app = MagicMock()

    with patch(
        f"{_TASK_CREATION}.get_first_indexing_hold",
        return_value=MagicMock() if held else None,
    ):
        attempt_id = try_creating_backfill_attempt(
            celery_app=celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            backfill=_backfill_spec(_OVERRIDE_CONFIG),
            db_session=db_session,
            r=MagicMock(),
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        )

    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.connector_credential_pair_id == cc_pair.id)
        .all()
    )
    if not expect_created:
        assert attempt_id is None
        assert attempts == []
        celery_app.send_task.assert_not_called()
        return

    assert attempt_id is not None
    assert [a.id for a in attempts] == [attempt_id]
    attempt = attempts[0]
    assert attempt.is_backfill
    assert attempt.connector_config_hash == compute_connector_config_hash(
        _OVERRIDE_CONFIG
    )
    celery_app.send_task.assert_called_once()
    send_kwargs = celery_app.send_task.call_args.kwargs
    assert send_kwargs["kwargs"]["index_attempt_id"] == attempt_id
    assert send_kwargs["task_id"] == attempt.celery_task_id


def _run_extraction(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    attempt: IndexAttempt,
    mock_get_connector_runner: MagicMock,
    app: MagicMock | None = None,
    documents: list[Document] | None = None,
) -> None:
    connector_runner = MagicMock()
    connector_runner.run.return_value = iter(
        [(documents or [], None, None, MagicMock(has_more=False))]
    )
    connector_runner.connector.build_dummy_checkpoint.return_value = MagicMock(
        has_more=True
    )
    mock_get_connector_runner.return_value = connector_runner
    connector_document_extraction(
        app=app or MagicMock(),
        index_attempt_id=attempt.id,
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        callback=None,
    )
    db_session.expire_all()


@patch(f"{_RUN_DOCFETCHING}.get_document_batch_storage")
@patch(f"{_RUN_DOCFETCHING}.MemoryTracer")
@patch(f"{_RUN_DOCFETCHING}._get_connector_runner")
@patch(f"{_RUN_DOCFETCHING}.save_checkpoint")
@patch("onyx.background.indexing.checkpointing_utils.load_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_redis_client")
@patch(f"{_RUN_DOCFETCHING}.ensure_source_node_exists")
def test_backfill_and_normal_runs_keep_separate_windows_and_checkpoints(
    mock_ensure_source_node_exists: MagicMock,  # noqa: ARG001
    mock_get_redis_client: MagicMock,  # noqa: ARG001
    mock_load_checkpoint: MagicMock,
    mock_save_checkpoint: MagicMock,  # noqa: ARG001
    mock_get_connector_runner: MagicMock,
    mock_memory_tracer_class: MagicMock,  # noqa: ARG001
    mock_get_batch_storage: MagicMock,
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    mock_load_checkpoint.return_value = ConnectorCheckpoint(has_more=True)
    cursor = _NORMAL_END - timedelta(days=1)
    normal_window_start = cursor - timedelta(minutes=POLL_CONNECTOR_OFFSET)
    _add_normal_attempt(
        db_session,
        cc_pair.id,
        search_settings.id,
        IndexingStatus.SUCCESS,
        poll_range_end=cursor,
    )
    failed_normal = _add_normal_attempt(
        db_session,
        cc_pair.id,
        search_settings.id,
        IndexingStatus.FAILED,
        poll_range_end=_NORMAL_END,
        poll_range_start=normal_window_start,
    )

    # the backfill runs exactly its window with the override config, starts
    # fresh, and leaves the failed normal attempt's checkpoint alone
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    backfill.status = IndexingStatus.IN_PROGRESS
    db_session.commit()
    _run_extraction(
        db_session, cc_pair.id, search_settings.id, backfill, mock_get_connector_runner
    )

    refreshed_backfill = db_session.get(IndexAttempt, backfill.id)
    assert refreshed_backfill is not None
    assert refreshed_backfill.poll_range_start == _BACKFILL_START
    assert refreshed_backfill.poll_range_end == _BACKFILL_END
    assert refreshed_backfill.connector_config_hash == compute_connector_config_hash(
        _OVERRIDE_CONFIG
    )
    assert mock_get_connector_runner.call_args.kwargs["start_time"] == _BACKFILL_START
    assert mock_get_connector_runner.call_args.kwargs["end_time"] == _BACKFILL_END
    mock_load_checkpoint.assert_not_called()
    assert mock_get_batch_storage.call_args.kwargs["is_backfill"] is True
    mock_get_connector_runner.return_value.connector.build_dummy_checkpoint.assert_called_once()

    # the backfill fails; the next normal attempt still resumes the failed
    # normal attempt's window and checkpoint
    _finish(db_session, refreshed_backfill, IndexingStatus.FAILED)
    normal = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"test_next_normal_{uuid4().hex[:8]}",
    )
    db_session.add(normal)
    db_session.commit()
    _run_extraction(
        db_session, cc_pair.id, search_settings.id, normal, mock_get_connector_runner
    )

    refreshed_normal = db_session.get(IndexAttempt, normal.id)
    assert refreshed_normal is not None
    assert refreshed_normal.poll_range_end == _NORMAL_END
    assert refreshed_normal.poll_range_start == normal_window_start
    assert refreshed_normal.connector_config_hash == compute_connector_config_hash(
        _CONFIG
    )
    assert mock_load_checkpoint.call_args.kwargs["index_attempt_id"] == (
        failed_normal.id
    )
    assert mock_get_batch_storage.call_args.kwargs["is_backfill"] is False


def _docprocessing_kwargs(app: MagicMock) -> list[dict[str, Any]]:
    return [
        send_call.kwargs["kwargs"]
        for send_call in app.send_task.call_args_list
        if send_call.args[0] == OnyxCeleryTask.DOCPROCESSING_TASK
    ]


@patch(f"{_RUN_DOCFETCHING}.get_source_node_id_from_cache", return_value=None)
@patch(f"{_RUN_DOCFETCHING}.get_document_batch_storage")
@patch(f"{_RUN_DOCFETCHING}.MemoryTracer")
@patch(f"{_RUN_DOCFETCHING}._get_connector_runner")
@patch(f"{_RUN_DOCFETCHING}.save_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_redis_client")
@patch(f"{_RUN_DOCFETCHING}.ensure_source_node_exists")
def test_only_backfill_batches_send_is_backfill(
    mock_ensure_source_node_exists: MagicMock,  # noqa: ARG001
    mock_get_redis_client: MagicMock,  # noqa: ARG001
    mock_save_checkpoint: MagicMock,  # noqa: ARG001
    mock_get_connector_runner: MagicMock,
    mock_memory_tracer_class: MagicMock,  # noqa: ARG001
    mock_get_batch_storage: MagicMock,  # noqa: ARG001
    mock_get_source_node_id: MagicMock,  # noqa: ARG001
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    """A worker from before backfills rejects an unknown kwarg, so a normal
    batch does not send ``is_backfill``."""
    document = Document(
        id=f"backfill_kwargs_{uuid4().hex[:8]}",
        sections=[TextSection(text="text")],
        source=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier="doc",
        metadata={},
    )
    normal = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=True,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"test_kwargs_normal_{uuid4().hex[:8]}",
    )
    db_session.add(normal)
    db_session.commit()
    normal_app = MagicMock()
    _run_extraction(
        db_session,
        cc_pair.id,
        search_settings.id,
        normal,
        mock_get_connector_runner,
        app=normal_app,
        documents=[document],
    )
    _finish(db_session, normal, IndexingStatus.SUCCESS)

    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    backfill.status = IndexingStatus.IN_PROGRESS
    db_session.commit()
    backfill_app = MagicMock()
    _run_extraction(
        db_session,
        cc_pair.id,
        search_settings.id,
        backfill,
        mock_get_connector_runner,
        app=backfill_app,
        documents=[document],
    )

    normal_kwargs = _docprocessing_kwargs(normal_app)
    backfill_kwargs = _docprocessing_kwargs(backfill_app)
    assert len(normal_kwargs) == 1
    assert "is_backfill" not in normal_kwargs[0]
    assert len(backfill_kwargs) == 1
    assert backfill_kwargs[0]["is_backfill"] is True


@patch(f"{_RUN_DOCFETCHING}.get_document_batch_storage")
@patch(f"{_RUN_DOCFETCHING}.MemoryTracer")
@patch(f"{_RUN_DOCFETCHING}._get_connector_runner")
@patch(f"{_RUN_DOCFETCHING}.save_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_redis_client")
@patch(f"{_RUN_DOCFETCHING}.ensure_source_node_exists")
def test_backfill_validation_error_does_not_mark_pair_invalid(
    mock_ensure_source_node_exists: MagicMock,  # noqa: ARG001
    mock_get_redis_client: MagicMock,  # noqa: ARG001
    mock_save_checkpoint: MagicMock,  # noqa: ARG001
    mock_get_connector_runner: MagicMock,
    mock_memory_tracer_class: MagicMock,  # noqa: ARG001
    mock_get_batch_storage: MagicMock,  # noqa: ARG001
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    db_session.commit()
    # Enough recent validation failures that one more normal failure would
    # mark the pair invalid.
    for _ in range(5):
        failed = _add_normal_attempt(
            db_session,
            cc_pair.id,
            search_settings.id,
            IndexingStatus.CANCELED,
            poll_range_end=_NORMAL_END,
        )
        failed.error_msg = f"{CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX}bad scope"
    db_session.commit()
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    backfill.status = IndexingStatus.IN_PROGRESS
    db_session.commit()
    connector_runner = MagicMock()
    connector_runner.run.side_effect = ConnectorValidationError("bad scope")
    mock_get_connector_runner.return_value = connector_runner

    with pytest.raises(ConnectorValidationError):
        connector_document_extraction(
            app=MagicMock(),
            index_attempt_id=backfill.id,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            callback=None,
        )

    db_session.expire_all()
    db_session.refresh(cc_pair)
    assert cc_pair.status == ConnectorCredentialPairStatus.ACTIVE


@patch(f"{_RUN_DOCFETCHING}.record_blocking_validation_outcome")
@patch(f"{_RUN_DOCFETCHING}.instantiate_connector")
def test_backfill_connector_uses_override_config(
    mock_instantiate_connector: MagicMock,
    mock_record_outcome: MagicMock,
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    attempt = db_session.get(IndexAttempt, backfill.id)
    assert attempt is not None

    _get_connector_runner(
        db_session=db_session,
        attempt=attempt,
        batch_size=10,
        start_time=_BACKFILL_START,
        end_time=_BACKFILL_END,
        include_permissions=False,
    )

    assert (
        mock_instantiate_connector.call_args.kwargs["connector_specific_config"]
        == _OVERRIDE_CONFIG
    )
    # the pair's capability report describes its saved config only
    mock_record_outcome.assert_not_called()


def test_backfill_completion_leaves_pair_state_alone(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    cc_pair.status = ConnectorCredentialPairStatus.INITIAL_INDEXING
    db_session.commit()
    backfill = _create_backfill(db_session, cc_pair.id, search_settings.id)
    backfill.status = IndexingStatus.IN_PROGRESS
    backfill.total_batches = 0
    db_session.commit()

    storage = MagicMock()
    check_indexing_completion(
        backfill.id,
        CoordinationStatus(
            found=True,
            total_batches=0,
            completed_batches=0,
            total_failures=0,
            total_docs=0,
            total_chunks=0,
        ),
        storage,
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
    )

    db_session.expire_all()
    refreshed_attempt = db_session.get(IndexAttempt, backfill.id)
    db_session.refresh(cc_pair)
    assert refreshed_attempt is not None
    assert refreshed_attempt.status == IndexingStatus.SUCCESS
    assert cc_pair.last_successful_index_time is None
    assert cc_pair.status == ConnectorCredentialPairStatus.INITIAL_INDEXING
    storage.cleanup_all_batches.assert_called_once()


@pytest.mark.parametrize(
    "source,expected",
    [
        (DocumentSource.SLACK, True),
        (DocumentSource.WEB, False),
        (DocumentSource.FILE, False),
    ],
)
def test_source_supports_windowed_runs(source: DocumentSource, expected: bool) -> None:
    assert source_supports_windowed_runs(source) is expected
