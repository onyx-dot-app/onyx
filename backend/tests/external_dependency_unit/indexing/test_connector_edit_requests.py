"""The requests a connector edit puts on a cc-pair. A restart stops the pair's
active attempts without the stop fence and has the beat create a fresh one. A
prune request runs once without prune_freq, waits for pause and for a running
prune, and is cleared by the prune it caused. A prune-after-reindex request
turns into a prune request only when a full re-index started after it
succeeds; the manual re-index never prunes."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import (
    _kickoff_indexing_tasks,
    check_indexing_completion,
    monitor_indexing_attempt_progress,
)
from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.background.celery.tasks.pruning.tasks import (
    _is_pruning_due,
    monitor_ccpair_pruning_taskset,
    try_creating_prune_generator_task,
)
from onyx.background.indexing.attempt_restart import revoke_restarted_attempt_tasks
from onyx.db.connector_edit_requests import (
    get_reindex_request_backoff,
    request_attempt_restart__no_commit,
    request_full_reindex__no_commit,
    request_prune__no_commit,
    request_prune_after_reindex__no_commit,
    request_retry_delay,
)
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    IndexingMode,
    IndexingStatus,
    SyncType,
)
from onyx.db.indexing_coordination import CoordinationStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    SearchSettings,
    SyncRecord,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents import connector as connector_api
from onyx.server.documents.connector import trigger_indexing_for_cc_pair
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_COMPLETED = CoordinationStatus(
    found=True,
    total_batches=0,
    completed_batches=0,
    total_failures=0,
    total_docs=0,
    total_chunks=0,
)


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
        RedisConnector(get_current_tenant_id(), pair.id).prune.reset()
        db_session.execute(
            delete(IndexAttempt).where(
                IndexAttempt.connector_credential_pair_id == pair.id
            )
        )
        db_session.execute(
            delete(SyncRecord).where(
                SyncRecord.entity_id == pair.id,
                SyncRecord.sync_type == SyncType.PRUNING,
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def search_settings(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> SearchSettings:
    return get_current_search_settings(db_session)


def _add_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    status: IndexingStatus,
    *,
    with_task: bool = True,
    is_backfill: bool = False,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=status,
        celery_task_id=f"test_restart_{uuid4().hex[:8]}" if with_task else None,
        time_started=(
            datetime.now(tz=timezone.utc)
            if status == IndexingStatus.IN_PROGRESS
            else None
        ),
        is_backfill=is_backfill,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _run_beat(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    db_session.expire_all()
    _kickoff_indexing_tasks(
        celery_app=MagicMock(),
        db_session=db_session,
        search_settings=search_settings,
        cc_pair_ids=[cc_pair.id],
        secondary_index_building=False,
        redis_client=get_redis_client(),
        lock_beat=MagicMock(),
        tenant_id=get_current_tenant_id(),
    )


def _attempts(db_session: Session, cc_pair_id: int) -> list[IndexAttempt]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(IndexAttempt)
            .where(IndexAttempt.connector_credential_pair_id == cc_pair_id)
            .order_by(IndexAttempt.id)
        ).all()
    )


def _complete(db_session: Session, attempt: IndexAttempt) -> None:
    attempt.status = IndexingStatus.IN_PROGRESS
    attempt.time_started = datetime.now(tz=timezone.utc)
    attempt.total_batches = 0
    db_session.commit()
    check_indexing_completion(
        attempt.id, _COMPLETED, MagicMock(), get_current_tenant_id()
    )
    db_session.expire_all()


def test_restart_stops_every_active_attempt_without_the_stop_fence(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    waiting = _add_attempt(
        db_session,
        cc_pair.id,
        search_settings.id,
        IndexingStatus.NOT_STARTED,
        with_task=False,
    )
    queued = _add_attempt(
        db_session, cc_pair.id, search_settings.id, IndexingStatus.NOT_STARTED
    )
    running = _add_attempt(
        db_session, cc_pair.id, search_settings.id, IndexingStatus.IN_PROGRESS
    )
    backfill = _add_attempt(
        db_session,
        cc_pair.id,
        search_settings.id,
        IndexingStatus.IN_PROGRESS,
        is_backfill=True,
    )
    finished = _add_attempt(
        db_session, cc_pair.id, search_settings.id, IndexingStatus.SUCCESS
    )

    task_ids = request_attempt_restart__no_commit(
        db_session, cc_pair.id, IndexingMode.UPDATE
    )
    db_session.commit()

    assert set(task_ids) == {
        queued.celery_task_id,
        running.celery_task_id,
        backfill.celery_task_id,
    }
    by_id = {attempt.id: attempt for attempt in _attempts(db_session, cc_pair.id)}
    # The held first attempt ends at once and stays undispatched.
    assert by_id[waiting.id].status == IndexingStatus.CANCELED
    assert by_id[waiting.id].time_started is None
    assert not by_id[waiting.id].cancellation_requested
    for attempt_id in (queued.id, running.id, backfill.id):
        assert by_id[attempt_id].cancellation_requested
    assert not by_id[finished.id].cancellation_requested

    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger == IndexingMode.UPDATE
    assert not RedisConnector(get_current_tenant_id(), cc_pair.id).stop.fenced

    celery_app = MagicMock()
    revoke_restarted_attempt_tasks(celery_app, task_ids)
    assert {call.args[0] for call in celery_app.control.revoke.call_args_list} == set(
        task_ids
    )


def test_restart_creates_a_fresh_attempt_once_the_old_one_ends(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    running = _add_attempt(
        db_session, cc_pair.id, search_settings.id, IndexingStatus.IN_PROGRESS
    )
    request_attempt_restart__no_commit(db_session, cc_pair.id, IndexingMode.REINDEX)
    db_session.commit()

    # The old attempt still blocks creation, and the trigger waits.
    _run_beat(db_session, cc_pair, search_settings)
    assert [a.id for a in _attempts(db_session, cc_pair.id)] == [running.id]
    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger == IndexingMode.REINDEX

    monitor_indexing_attempt_progress(running, get_current_tenant_id(), db_session)
    _run_beat(db_session, cc_pair, search_settings)

    old, fresh = _attempts(db_session, cc_pair.id)
    assert old.status == IndexingStatus.CANCELED
    assert fresh.status == IndexingStatus.NOT_STARTED
    assert fresh.from_beginning
    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger is None


def test_restart_keeps_a_pending_reindex_trigger(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    cc_pair.indexing_trigger = IndexingMode.REINDEX
    db_session.commit()

    request_attempt_restart__no_commit(db_session, cc_pair.id, IndexingMode.UPDATE)
    db_session.commit()

    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger == IndexingMode.REINDEX


def test_restart_on_a_paused_pair_fires_on_resume(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()

    assert (
        request_attempt_restart__no_commit(db_session, cc_pair.id, IndexingMode.REINDEX)
        == []
    )
    db_session.commit()

    _run_beat(db_session, cc_pair, search_settings)
    assert _attempts(db_session, cc_pair.id) == []
    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger == IndexingMode.REINDEX

    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    (attempt,) = _attempts(db_session, cc_pair.id)
    assert attempt.from_beginning


def test_requests_refuse_a_deleting_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    running = _add_attempt(
        db_session, cc_pair.id, search_settings.id, IndexingStatus.IN_PROGRESS
    )
    cc_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()

    for request in (
        lambda: request_attempt_restart__no_commit(
            db_session, cc_pair.id, IndexingMode.UPDATE
        ),
        lambda: request_prune__no_commit(db_session, cc_pair.id),
        lambda: request_prune_after_reindex__no_commit(db_session, cc_pair.id),
    ):
        with pytest.raises(OnyxError) as exc_info:
            request()
        assert exc_info.value.error_code == OnyxErrorCode.CONFLICT
        db_session.rollback()

    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger is None
    assert cc_pair.prune_requested_at is None
    assert cc_pair.prune_after_reindex_requested_at is None
    (attempt,) = _attempts(db_session, cc_pair.id)
    assert attempt.id == running.id
    assert not attempt.cancellation_requested


def test_prune_request_is_due_without_prune_freq_and_waits_for_resume(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    assert cc_pair.connector.prune_freq is None
    assert not _is_pruning_due(cc_pair)

    request_prune__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    assert _is_pruning_due(cc_pair)

    cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()
    assert not _is_pruning_due(cc_pair)
    assert cc_pair.prune_requested_at is not None

    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    db_session.commit()
    assert _is_pruning_due(cc_pair)


def _finish_prune(
    db_session: Session, redis_connector: RedisConnector, tenant_id: str
) -> None:
    redis_connector.prune.generator_complete = 0
    monitor_ccpair_pruning_taskset(
        tenant_id,
        redis_connector.prune.fence_key.encode(),
        get_redis_client(),
        db_session,
    )
    db_session.expire_all()


def test_prune_request_waits_for_a_running_prune_and_clears_on_its_own(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Prunes of other pairs on the shared Redis must not block this one.
    monkeypatch.setattr(pruning_tasks, "ALLOW_SIMULTANEOUS_PRUNING", True)
    tenant_id = get_current_tenant_id()
    redis_connector = RedisConnector(tenant_id, cc_pair.id)
    r = get_redis_client()

    # A prune dispatched before the request runs.
    redis_connector.prune.set_fence(
        RedisConnectorPrunePayload(
            id="older",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id="older_task",
        )
    )
    request_prune__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    requested_at = cc_pair.prune_requested_at
    assert requested_at is not None

    assert (
        try_creating_prune_generator_task(
            MagicMock(), cc_pair, db_session, r, tenant_id
        )
        is None
    )

    # Its success leaves the request for a prune of its own.
    _finish_prune(db_session, redis_connector, tenant_id)
    db_session.refresh(cc_pair)
    assert cc_pair.last_pruned is not None
    assert cc_pair.prune_requested_at == requested_at
    assert _is_pruning_due(cc_pair)

    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "requested_task"
    assert (
        try_creating_prune_generator_task(celery_app, cc_pair, db_session, r, tenant_id)
        is not None
    )
    payload = redis_connector.prune.payload
    assert payload is not None
    assert payload.prune_requested_at == requested_at

    _finish_prune(db_session, redis_connector, tenant_id)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at is None
    assert not _is_pruning_due(cc_pair)


def test_failed_prune_keeps_the_request(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pruning_tasks, "ALLOW_SIMULTANEOUS_PRUNING", True)
    tenant_id = get_current_tenant_id()
    redis_connector = RedisConnector(tenant_id, cc_pair.id)

    request_prune__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    requested_at = cc_pair.prune_requested_at
    assert requested_at is not None
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "requested_task"
    assert (
        try_creating_prune_generator_task(
            celery_app, cc_pair, db_session, get_redis_client(), tenant_id
        )
        is not None
    )

    redis_connector.prune.set_generator_failed()
    _finish_prune(db_session, redis_connector, tenant_id)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at == requested_at
    assert cc_pair.last_pruned is None


def test_prune_success_keeps_a_newer_request(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pruning_tasks, "ALLOW_SIMULTANEOUS_PRUNING", True)
    tenant_id = get_current_tenant_id()
    redis_connector = RedisConnector(tenant_id, cc_pair.id)

    request_prune__no_commit(db_session, cc_pair.id)
    db_session.commit()
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "requested_task"
    assert (
        try_creating_prune_generator_task(
            celery_app, cc_pair, db_session, get_redis_client(), tenant_id
        )
        is not None
    )

    # An edit while the prune runs asks again.
    request_prune__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    newer = cc_pair.prune_requested_at

    _finish_prune(db_session, redis_connector, tenant_id)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at == newer


def test_prune_after_reindex_waits_for_a_successful_full_reindex(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    # Unscheduled: only the pending request keeps the pair due after the
    # first attempt spends the trigger.
    assert cc_pair.connector.refresh_freq is None

    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    requested_at = cc_pair.prune_after_reindex_requested_at
    assert requested_at is not None
    assert cc_pair.indexing_trigger == IndexingMode.REINDEX

    _run_beat(db_session, cc_pair, search_settings)
    (first,) = _attempts(db_session, cc_pair.id)
    assert first.from_beginning
    assert first.prune_after_reindex_requested_at == requested_at

    # A failed re-index passes the request to the next run, which is a full
    # re-index even without a trigger, once the backoff passes.
    first.status = IndexingStatus.FAILED
    first.time_updated = datetime.now(tz=timezone.utc) - timedelta(minutes=6)
    db_session.commit()
    db_session.refresh(cc_pair)
    assert cc_pair.indexing_trigger is None
    assert cc_pair.prune_requested_at is None

    _run_beat(db_session, cc_pair, search_settings)
    _, second = _attempts(db_session, cc_pair.id)
    assert second.from_beginning
    assert second.prune_after_reindex_requested_at == requested_at

    _complete(db_session, second)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at is not None
    assert cc_pair.prune_after_reindex_requested_at is None

    # With the request served, the unscheduled pair is not due.
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 2

    # A scheduled run is incremental again.
    cc_pair.connector.refresh_freq = 0
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    *_, third = _attempts(db_session, cc_pair.id)
    assert not third.from_beginning
    assert third.prune_after_reindex_requested_at is None


def test_prune_after_reindex_keeps_a_newer_request(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    (attempt,) = _attempts(db_session, cc_pair.id)

    # A second edit asks again while the first re-index runs.
    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    db_session.refresh(cc_pair)
    newer = cc_pair.prune_after_reindex_requested_at
    assert newer != attempt.prune_after_reindex_requested_at

    _complete(db_session, attempt)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at is not None
    assert cc_pair.prune_after_reindex_requested_at == newer


def test_manual_reindex_does_not_prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_api, "client_app", MagicMock())
    assert (
        trigger_indexing_for_cc_pair(
            [],
            cc_pair.connector_id,
            True,
            get_current_tenant_id(),
            db_session,
        )
        == 1
    )

    _run_beat(db_session, cc_pair, search_settings)
    (attempt,) = _attempts(db_session, cc_pair.id)
    assert attempt.from_beginning
    assert attempt.prune_after_reindex_requested_at is None

    _complete(db_session, attempt)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_requested_at is None


def _fail(
    db_session: Session, attempt: IndexAttempt, *, minutes_ago: float = 0
) -> None:
    attempt.status = IndexingStatus.FAILED
    attempt.time_updated = datetime.now(tz=timezone.utc) - timedelta(
        minutes=minutes_ago
    )
    db_session.commit()


def test_request_retry_delay_doubles_up_to_a_cap() -> None:
    assert request_retry_delay(1) == timedelta(minutes=5)
    assert request_retry_delay(2) == timedelta(minutes=10)
    assert request_retry_delay(3) == timedelta(minutes=20)
    assert request_retry_delay(50) == timedelta(hours=6)


def test_prune_after_reindex_backs_off_after_failed_attempts(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()

    # The first attempt is not delayed.
    _run_beat(db_session, cc_pair, search_settings)
    (first,) = _attempts(db_session, cc_pair.id)

    # One failure waits 5 minutes.
    _fail(db_session, first)
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 1
    _fail(db_session, first, minutes_ago=6)
    _run_beat(db_session, cc_pair, search_settings)
    _, second = _attempts(db_session, cc_pair.id)
    assert second.from_beginning

    # Two failures wait 10 minutes, from the latest failure.
    _fail(db_session, second, minutes_ago=6)
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 2
    backoff = get_reindex_request_backoff(db_session, cc_pair.id, search_settings.id)
    assert backoff is not None
    assert backoff.failure_count == 2

    _fail(db_session, first, minutes_ago=16)
    _fail(db_session, second, minutes_ago=11)
    _run_beat(db_session, cc_pair, search_settings)
    *_, third = _attempts(db_session, cc_pair.id)
    assert third.id != second.id
    assert third.from_beginning

    # A manual trigger does not wait for the backoff.
    _fail(db_session, third)
    db_session.refresh(cc_pair)
    cc_pair.indexing_trigger = IndexingMode.UPDATE
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 4


def test_a_served_request_resets_the_backoff(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    (first,) = _attempts(db_session, cc_pair.id)
    _fail(db_session, first, minutes_ago=6)
    _run_beat(db_session, cc_pair, search_settings)
    _, second = _attempts(db_session, cc_pair.id)

    _complete(db_session, second)
    db_session.refresh(cc_pair)
    assert cc_pair.prune_after_reindex_requested_at is None

    # A new request starts with no backoff, though an attempt failed before.
    request_prune_after_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    assert (
        get_reindex_request_backoff(db_session, cc_pair.id, search_settings.id) is None
    )
    _run_beat(db_session, cc_pair, search_settings)
    *_, third = _attempts(db_session, cc_pair.id)
    assert third.id != second.id
    assert third.from_beginning


def test_full_reindex_request_backs_off_after_failed_attempts(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    request_full_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    (first,) = _attempts(db_session, cc_pair.id)
    assert first.full_reindex_requested_at is not None

    _fail(db_session, first)
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 1
    backoff = get_reindex_request_backoff(db_session, cc_pair.id, search_settings.id)
    assert backoff is not None
    assert backoff.failure_count == 1

    _fail(db_session, first, minutes_ago=6)
    _run_beat(db_session, cc_pair, search_settings)
    _, second = _attempts(db_session, cc_pair.id)
    assert second.from_beginning

    # A new request starts with no backoff.
    _fail(db_session, second)
    request_full_reindex__no_commit(db_session, cc_pair.id)
    db_session.commit()
    assert (
        get_reindex_request_backoff(db_session, cc_pair.id, search_settings.id) is None
    )
