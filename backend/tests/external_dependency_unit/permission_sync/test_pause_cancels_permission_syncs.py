"""A pause ends the pair's doc permission sync and queued group sync as
CANCELED, not FAILED. A doc permission sync that sees the pause's stop signal
keeps the cancel, a running group sync finishes, and a manual permission sync
of a paused pair is refused."""

import time
from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from ee.onyx.server.documents import cc_pair as ee_cc_pair_api
from ee.onyx.server.documents.cc_pair import sync_cc_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    PermissionSyncStatus,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    User,
)
from onyx.db.permission_sync_attempt import (
    get_doc_permission_sync_attempt,
    get_external_group_sync_attempt,
    get_open_doc_permission_sync_attempt,
    mark_doc_permission_sync_attempt_failed,
    mark_doc_permission_sync_attempt_in_progress,
    mark_external_group_sync_attempt_in_progress,
    try_create_doc_permission_sync_attempt,
    try_create_external_group_sync_attempt,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_stop import RedisConnectorStop
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents.cc_pair import update_cc_pair_status
from onyx.server.documents.models import CCStatusUpdateRequest
from onyx.utils.threadpool_concurrency import run_in_background, wait_on_background
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_PAUSE_REASON = "Canceled: the connector was paused"
_WAIT_SECONDS = 15.0


def _sync_cc_pair(
    db_session: Session,
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    pair.access_type = AccessType.SYNC
    db_session.commit()
    yield pair
    db_session.rollback()
    RedisConnector(get_current_tenant_id(), pair.id).stop.set_fence(False)
    db_session.execute(
        delete(DocPermissionSyncAttempt).where(
            DocPermissionSyncAttempt.connector_credential_pair_id == pair.id
        )
    )
    db_session.execute(
        delete(ExternalGroupPermissionSyncAttempt).where(
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id == pair.id
        )
    )
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _sync_cc_pair(db_session)


@pytest.fixture
def other_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _sync_cc_pair(db_session)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "perm_sync_pause_admin", is_admin=True)
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def _pause(db_session: Session, cc_pair: ConnectorCredentialPair, admin: User) -> None:
    update_cc_pair_status(
        cc_pair.id,
        CCStatusUpdateRequest(status=ConnectorCredentialPairStatus.PAUSED),
        user=admin,
        db_session=db_session,
    )


def _running_doc_permission_sync(db_session: Session, cc_pair_id: int) -> int:
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair_id, f"task-{uuid4().hex[:8]}", db_session
    )
    assert attempt_id is not None
    mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
    return attempt_id


def _waits_on_a_lock(backend_pid: int) -> bool:
    with get_session_with_current_tenant() as session:
        return bool(
            session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE pid = :pid AND wait_event_type = 'Lock'"
                ),
                {"pid": backend_pid},
            )
        )


class _StopSignalFailureWrite:
    """The failure write of a doc permission sync that stopped on the stop
    signal, run on its own thread and session."""

    def __init__(self, attempt_id: int) -> None:
        self._attempt_id = attempt_id
        self._backend_pid: int | None = None
        self._thread = run_in_background(self._write)

    def _write(self) -> None:
        with get_session_with_current_tenant() as session:
            self._backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
            mark_doc_permission_sync_attempt_failed(
                self._attempt_id,
                session,
                error_message="Permission sync stopped: stop signal set",
            )

    def wait_until_done_or_blocked(self) -> None:
        deadline = time.monotonic() + _WAIT_SECONDS
        while self._thread.is_alive():
            if self._backend_pid is not None and _waits_on_a_lock(self._backend_pid):
                return
            assert time.monotonic() < deadline, "the failure write never ran"
            time.sleep(0.05)

    def finish(self) -> None:
        self._thread.join(_WAIT_SECONDS)
        assert not self._thread.is_alive(), "the failure write never finished"
        wait_on_background(self._thread)


def test_a_doc_permission_sync_that_sees_the_pause_keeps_the_cancel(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    other_cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = _running_doc_permission_sync(db_session, cc_pair.id)
    other_attempt_id = _running_doc_permission_sync(db_session, other_cc_pair.id)
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    # A running sync polls the stop signal on every element, so it can record
    # its failure the moment the pause sets the signal.
    failure_write: _StopSignalFailureWrite | None = None
    set_fence = RedisConnectorStop.set_fence

    def set_fence_then_fail_like_the_sync(
        stop: RedisConnectorStop, value: bool
    ) -> None:
        nonlocal failure_write
        set_fence(stop, value)
        if value:
            failure_write = _StopSignalFailureWrite(attempt_id)
            failure_write.wait_until_done_or_blocked()

    monkeypatch.setattr(
        RedisConnectorStop, "set_fence", set_fence_then_fail_like_the_sync
    )

    try:
        _pause(db_session, cc_pair, admin)
    finally:
        # Releases the attempt row if the pause failed before its commit
        db_session.rollback()
        if failure_write is not None:
            failure_write.finish()

    assert failure_write is not None
    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.CANCELED
    assert attempt.error_message == _PAUSE_REASON
    assert RedisConnector(get_current_tenant_id(), cc_pair.id).stop.fenced
    other_attempt = get_doc_permission_sync_attempt(db_session, other_attempt_id)
    assert other_attempt is not None
    assert other_attempt.status == PermissionSyncStatus.IN_PROGRESS


@pytest.mark.parametrize(
    ("status", "status_after_pause"),
    [
        (PermissionSyncStatus.NOT_STARTED, PermissionSyncStatus.CANCELED),
        (PermissionSyncStatus.IN_PROGRESS, PermissionSyncStatus.IN_PROGRESS),
    ],
)
def test_pause_cancels_a_queued_group_sync_and_lets_a_running_one_finish(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
    status: PermissionSyncStatus,
    status_after_pause: PermissionSyncStatus,
) -> None:
    attempt_id = try_create_external_group_sync_attempt(
        cc_pair.id, f"task-{uuid4().hex[:8]}", db_session
    )
    assert attempt_id is not None
    if status == PermissionSyncStatus.IN_PROGRESS:
        mark_external_group_sync_attempt_in_progress(attempt_id, db_session)
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    _pause(db_session, cc_pair, admin)

    db_session.expire_all()
    attempt = get_external_group_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == status_after_pause
    if status_after_pause == PermissionSyncStatus.CANCELED:
        assert attempt.error_message == _PAUSE_REASON


def test_manual_permission_sync_of_a_paused_pair_is_refused(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()
    api_celery = MagicMock()
    monkeypatch.setattr(ee_cc_pair_api, "client_app", api_celery)

    with pytest.raises(OnyxError) as exc_info:
        sync_cc_pair(cc_pair.id, user=admin, db_session=db_session)

    assert exc_info.value.error_code == OnyxErrorCode.CONFLICT
    api_celery.send_task.assert_not_called()
    assert get_open_doc_permission_sync_attempt(cc_pair.id, db_session) is None
