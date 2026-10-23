"""A prune that a pause or a deletion abandons ends with a CANCELED sync
record and no prune fence, and the deletion beat leaves a paused pair's stop
signal in place. Deleting a paused pair still revokes its blocking tasks and
waits for them before it resets their fences. A generator runs only under its
own fence, and a paused pair refuses a manual prune."""

import time
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.connector_deletion import (
    tasks as connector_deletion_tasks,
)
from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import ConnectorCredentialPairStatus, SyncStatus, SyncType
from onyx.db.models import ConnectorCredentialPair, SyncRecord, User
from onyx.db.sync_record import fetch_latest_sync_record, insert_sync_record
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents.cc_pair import prune_cc_pair, update_cc_pair_status
from onyx.server.documents.models import CCStatusUpdateRequest
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_PRUNE_TASK_ID = "prune-cancel-test-task"


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    redis_connector = RedisConnector(get_current_tenant_id(), pair.id)
    yield pair
    redis_connector.prune.reset()
    redis_connector.delete.reset()
    redis_connector.stop.set_fence(False)
    redis_connector.stop.clear_timeout()
    db_session.rollback()
    db_session.execute(delete(SyncRecord).where(SyncRecord.entity_id == pair.id))
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "prune_cancel_admin", is_admin=True)
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def _set_status(
    db_session: Session,
    pair: ConnectorCredentialPair,
    status: ConnectorCredentialPairStatus,
) -> None:
    pair.status = status
    db_session.commit()


def _queue_prune(db_session: Session, pair: ConnectorCredentialPair) -> RedisConnector:
    """Mirrors try_creating_prune_generator_task: an IN_PROGRESS record and a
    fence for a generator that has not started."""
    insert_sync_record(db_session, pair.id, SyncType.PRUNING)
    redis_connector = RedisConnector(get_current_tenant_id(), pair.id)
    redis_connector.prune.set_fence(
        RedisConnectorPrunePayload(
            id="prune-cancel-test",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id=_PRUNE_TASK_ID,
        )
    )
    return redis_connector


def _prune_status(db_session: Session, pair: ConnectorCredentialPair) -> SyncStatus:
    db_session.expire_all()
    record = fetch_latest_sync_record(db_session, pair.id, SyncType.PRUNING)
    assert record is not None
    return record.sync_status


def _run_deletion_beat(
    pair: ConnectorCredentialPair, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only this pair, without fence validation, and clear of a running beat.
    monkeypatch.setattr(
        connector_deletion_tasks,
        "get_connector_credential_pairs",
        lambda _db_session: [pair],
    )
    monkeypatch.setattr(
        connector_deletion_tasks, "celery_get_broker_client", MagicMock()
    )
    monkeypatch.setattr(
        connector_deletion_tasks, "validate_connector_deletion_fences", MagicMock()
    )
    monkeypatch.setattr(
        OnyxRedisLocks,
        "CHECK_CONNECTOR_DELETION_BEAT_LOCK",
        f"prune-cancel-test-deletion-beat-lock-{pair.id}",
    )
    result = connector_deletion_tasks.check_for_connector_deletion_task.apply(
        kwargs={"tenant_id": get_current_tenant_id()}
    )
    assert result.successful(), result.traceback


def test_deletion_beat_keeps_a_paused_pairs_stop_signal(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.PAUSED)
    redis_connector = RedisConnector(get_current_tenant_id(), cc_pair.id)
    redis_connector.stop.set_fence(True)

    _run_deletion_beat(cc_pair, monkeypatch)

    assert redis_connector.stop.fenced


@pytest.mark.parametrize(
    "status",
    [ConnectorCredentialPairStatus.PAUSED, ConnectorCredentialPairStatus.DELETING],
)
def test_prune_generator_cancels_for_a_paused_or_deleting_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    status: ConnectorCredentialPairStatus,
) -> None:
    _set_status(db_session, cc_pair, status)
    redis_connector = _queue_prune(db_session, cc_pair)
    instantiate = MagicMock(side_effect=AssertionError("the prune enumerated"))
    monkeypatch.setattr(pruning_tasks, "instantiate_connector", instantiate)

    result = pruning_tasks.connector_pruning_generator_task.apply(
        kwargs={
            "cc_pair_id": cc_pair.id,
            "connector_id": cc_pair.connector_id,
            "credential_id": cc_pair.credential_id,
            "tenant_id": get_current_tenant_id(),
        },
        task_id=_PRUNE_TASK_ID,
    )

    assert result.successful(), result.traceback
    instantiate.assert_not_called()
    assert not redis_connector.prune.fenced
    assert _prune_status(db_session, cc_pair) == SyncStatus.CANCELED


def test_deletion_stop_timeout_cancels_the_prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.DELETING)
    redis_connector = _queue_prune(db_session, cc_pair)
    # The deletion beat already signaled stop, and its wait timed out.
    redis_connector.stop.set_fence(True)
    redis_connector.redis.set(redis_connector.stop.timeout_key, time.time() - 1)

    _run_deletion_beat(cc_pair, monkeypatch)

    assert not redis_connector.prune.fenced
    assert _prune_status(db_session, cc_pair) == SyncStatus.CANCELED


def test_deleting_a_paused_pair_revokes_and_waits_for_blocking_tasks(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.DELETING)
    redis_connector = _queue_prune(db_session, cc_pair)
    # The pause before the deletion left its stop signal.
    redis_connector.stop.set_fence(True)
    revoke = MagicMock()
    monkeypatch.setattr(
        connector_deletion_tasks, "revoke_tasks_blocking_deletion", revoke
    )

    _run_deletion_beat(cc_pair, monkeypatch)

    revoke.assert_called_once()
    assert redis_connector.stop.timeout_set
    assert not redis_connector.stop.timed_out
    assert redis_connector.prune.fenced
    assert _prune_status(db_session, cc_pair) == SyncStatus.IN_PROGRESS


def test_pause_cancels_a_queued_prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.ACTIVE)
    redis_connector = _queue_prune(db_session, cc_pair)
    api_celery = MagicMock()
    monkeypatch.setattr(cc_pair_api, "client_app", api_celery)

    update_cc_pair_status(
        cc_pair.id,
        CCStatusUpdateRequest(status=ConnectorCredentialPairStatus.PAUSED),
        user=admin,
        db_session=db_session,
    )

    api_celery.control.revoke.assert_called_once_with(_PRUNE_TASK_ID)
    assert not redis_connector.prune.fenced
    assert redis_connector.stop.fenced
    assert _prune_status(db_session, cc_pair) == SyncStatus.CANCELED


def test_prune_generator_leaves_a_newer_prune_alone(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.PAUSED)
    redis_connector = _queue_prune(db_session, cc_pair)
    newer = RedisConnectorPrunePayload(
        id="prune-cancel-test-newer",
        submitted=datetime.now(timezone.utc),
        started=datetime.now(timezone.utc),
        celery_task_id="prune-cancel-test-newer-task",
    )
    lock_row = pruning_tasks.lock_connector_credential_pair_row

    # A pause drops this run and a newer prune starts before it takes the lock.
    def _replace_then_lock(
        session: Session, cc_pair_id: int
    ) -> ConnectorCredentialPair | None:
        redis_connector.prune.set_fence(newer)
        return lock_row(session, cc_pair_id)

    monkeypatch.setattr(
        pruning_tasks, "lock_connector_credential_pair_row", _replace_then_lock
    )
    instantiate = MagicMock(side_effect=AssertionError("the prune enumerated"))
    monkeypatch.setattr(pruning_tasks, "instantiate_connector", instantiate)

    result = pruning_tasks.connector_pruning_generator_task.apply(
        kwargs={
            "cc_pair_id": cc_pair.id,
            "connector_id": cc_pair.connector_id,
            "credential_id": cc_pair.credential_id,
            "tenant_id": get_current_tenant_id(),
        },
        task_id=_PRUNE_TASK_ID,
    )

    assert result.successful(), result.traceback
    instantiate.assert_not_called()
    assert redis_connector.prune.payload == newer
    assert _prune_status(db_session, cc_pair) == SyncStatus.IN_PROGRESS


def test_prune_generator_skips_a_fence_it_does_not_own(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.ACTIVE)
    redis_connector = _queue_prune(db_session, cc_pair)
    queued_payload = redis_connector.prune.payload
    instantiate = MagicMock(side_effect=AssertionError("the prune enumerated"))
    monkeypatch.setattr(pruning_tasks, "instantiate_connector", instantiate)

    result = pruning_tasks.connector_pruning_generator_task.apply(
        kwargs={
            "cc_pair_id": cc_pair.id,
            "connector_id": cc_pair.connector_id,
            "credential_id": cc_pair.credential_id,
            "tenant_id": get_current_tenant_id(),
        },
        task_id="prune-cancel-test-stale-task",
    )

    assert result.successful(), result.traceback
    instantiate.assert_not_called()
    assert redis_connector.prune.payload == queued_payload
    assert _prune_status(db_session, cc_pair) == SyncStatus.IN_PROGRESS


def test_manual_prune_of_a_paused_pair_is_refused(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_status(db_session, cc_pair, ConnectorCredentialPairStatus.PAUSED)
    api_celery = MagicMock()
    monkeypatch.setattr(cc_pair_api, "client_app", api_celery)

    with pytest.raises(OnyxError) as exc_info:
        prune_cc_pair(cc_pair.id, user=admin, db_session=db_session)

    assert exc_info.value.error_code == OnyxErrorCode.CONFLICT
    api_celery.send_task.assert_not_called()
    assert not RedisConnector(get_current_tenant_id(), cc_pair.id).prune.fenced
