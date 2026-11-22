"""A pause ends the pair's doc permission sync and queued group sync as
CANCELED, not FAILED. A doc permission sync that sees the pause's stop signal
keeps the cancel, a dispatch that races the pause creates no attempt, the pause
waits for the sync's writes before it locks the pair and never under it, nor
makes a dispatch wait on the attempt, a running group sync stays open, and a
manual permission sync of a paused pair is refused."""

import threading
import time
from collections.abc import Callable, Generator
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from psycopg2.errors import LockNotAvailable
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
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
    lock_doc_permission_sync_attempt_if_owned,
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
_STOP_SIGNAL_FAILURE = "Permission sync stopped: stop signal set"
_WAIT_SECONDS = 15.0


def _perm_synced_cc_pair(
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
    yield from _perm_synced_cc_pair(db_session)


@pytest.fixture
def other_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _perm_synced_cc_pair(db_session)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "perm_sync_pause_admin", is_admin=True)
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def _pause(db_session: Session, cc_pair_id: int, admin: User) -> None:
    update_cc_pair_status(
        cc_pair_id,
        CCStatusUpdateRequest(status=ConnectorCredentialPairStatus.PAUSED),
        user=admin,
        db_session=db_session,
    )


def _pause_as(db_session: Session, cc_pair_id: int, admin_id: UUID) -> None:
    admin = db_session.get(User, admin_id)
    assert admin is not None
    _pause(db_session, cc_pair_id, admin)


def _running_doc_permission_sync(db_session: Session, cc_pair_id: int) -> int:
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair_id, f"task-{uuid4().hex[:8]}", db_session
    )
    assert attempt_id is not None
    mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
    return attempt_id


def _times_out_on_a_lock(call: Callable[[Session], None]) -> bool:
    """Runs the call on its own session with a short lock timeout."""
    with get_session_with_current_tenant() as session:
        session.execute(text("SET LOCAL lock_timeout = '200ms'"))
        try:
            call(session)
        except OperationalError as error:
            if not isinstance(error.orig, LockNotAvailable):
                raise
            return True
        return False


def _take_key_share_lock_on_pair(cc_pair_id: int) -> Callable[[Session], None]:
    """What a foreign key check on the pair's row does."""

    def take(session: Session) -> None:
        session.execute(
            select(ConnectorCredentialPair.id)
            .where(ConnectorCredentialPair.id == cc_pair_id)
            .with_for_update(read=True, key_share=True)
        )

    return take


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


class _CallOnItsOwnSession:
    """Runs a DB call on a background thread with its own session, so a test
    can check that it waits on a lock another transaction holds."""

    def __init__(self, call: Callable[[Session], int | None]) -> None:
        self._call = call
        self._backend_pid: int | None = None
        self._thread = run_in_background(self._run)

    def _run(self) -> int | None:
        with get_session_with_current_tenant() as session:
            self._backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
            return self._call(session)

    def wait_until_blocked(self) -> None:
        deadline = time.monotonic() + _WAIT_SECONDS
        while self._backend_pid is None or not _waits_on_a_lock(self._backend_pid):
            assert self._thread.is_alive(), "the call ended without waiting on a lock"
            assert time.monotonic() < deadline, "the call never waited on a lock"
            time.sleep(0.05)

    def result(self) -> int | None:
        self._thread.join(_WAIT_SECONDS)
        assert not self._thread.is_alive(), "the call never finished"
        return wait_on_background(self._thread)


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

    def record_stop_signal_failure(session: Session) -> None:
        mark_doc_permission_sync_attempt_failed(
            attempt_id, session, error_message=_STOP_SIGNAL_FAILURE
        )

    # A running sync polls the stop signal on every element, so its failure
    # write can come the moment the signal is set. It must wait for the pause.
    failure_write_waited: bool | None = None
    set_fence = RedisConnectorStop.set_fence

    def set_fence_then_record_a_failure(stop: RedisConnectorStop, value: bool) -> None:
        nonlocal failure_write_waited
        set_fence(stop, value)
        if value:
            failure_write_waited = _times_out_on_a_lock(record_stop_signal_failure)

    monkeypatch.setattr(
        RedisConnectorStop, "set_fence", set_fence_then_record_a_failure
    )

    _pause(db_session, cc_pair.id, admin)
    record_stop_signal_failure(db_session)

    assert failure_write_waited is True
    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.CANCELED
    assert attempt.error_message == _PAUSE_REASON
    assert RedisConnector(get_current_tenant_id(), cc_pair.id).stop.fenced
    other_attempt = get_doc_permission_sync_attempt(db_session, other_attempt_id)
    assert other_attempt is not None
    assert other_attempt.status == PermissionSyncStatus.IN_PROGRESS


def test_a_doc_permission_sync_dispatched_during_the_pause_is_not_created(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair_id = cc_pair.id
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    # A beat that read the pair as ACTIVE before the pause dispatches while
    # the pause holds the pair's row lock.
    dispatch: _CallOnItsOwnSession | None = None
    set_fence = RedisConnectorStop.set_fence

    def set_fence_then_dispatch(stop: RedisConnectorStop, value: bool) -> None:
        nonlocal dispatch
        set_fence(stop, value)
        if value:
            dispatch = _CallOnItsOwnSession(
                lambda session: try_create_doc_permission_sync_attempt(
                    cc_pair_id, f"task-{uuid4().hex[:8]}", session
                )
            )
            dispatch.wait_until_blocked()

    monkeypatch.setattr(RedisConnectorStop, "set_fence", set_fence_then_dispatch)

    try:
        _pause(db_session, cc_pair_id, admin)
    finally:
        # Releases the pair's row if the pause failed before its commit
        db_session.rollback()
        dispatched_attempt_id = dispatch.result() if dispatch else None

    assert dispatch is not None
    assert dispatched_attempt_id is None
    assert get_open_doc_permission_sync_attempt(cc_pair_id, db_session) is None


def test_the_pause_waits_for_sync_writes_before_it_locks_the_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair_id, admin_id = cc_pair.id, admin.id
    attempt_id = _running_doc_permission_sync(db_session, cc_pair_id)
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    # A sync write holds a share lock on its attempt until it commits, and it
    # can itself wait on rows whose writers need the pair's row.
    write_holds_lock = threading.Event()
    write_may_commit = threading.Event()

    def sync_write(session: Session) -> None:
        lock_doc_permission_sync_attempt_if_owned(attempt_id, session)
        write_holds_lock.set()
        assert write_may_commit.wait(_WAIT_SECONDS)
        session.commit()

    write = _CallOnItsOwnSession(sync_write)
    try:
        assert write_holds_lock.wait(_WAIT_SECONDS)
        pause = _CallOnItsOwnSession(
            lambda session: _pause_as(session, cc_pair_id, admin_id)
        )
        try:
            pause.wait_until_blocked()
            # Foreign key checks on the pair go on while the pause waits
            assert not _times_out_on_a_lock(_take_key_share_lock_on_pair(cc_pair_id))
        finally:
            write_may_commit.set()
            pause.result()
    finally:
        write_may_commit.set()
        write.result()

    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.CANCELED


def test_a_dispatch_holding_the_pair_does_not_wait_on_the_pauses_attempt_lock(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair_id, admin_id = cc_pair.id, admin.id
    attempt_id = _running_doc_permission_sync(db_session, cc_pair_id)
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    with get_session_with_current_tenant() as dispatch_session:
        # A dispatch holds its key share lock on the pair, so the pause holds
        # the open attempt and waits for the pair.
        dispatch_session.execute(text("SET LOCAL lock_timeout = '2s'"))
        _take_key_share_lock_on_pair(cc_pair_id)(dispatch_session)
        pause = _CallOnItsOwnSession(
            lambda session: _pause_as(session, cc_pair_id, admin_id)
        )
        try:
            pause.wait_until_blocked()
            # Only locked, not yet canceled: the insert sees an open attempt
            # and returns. On an updated row it would wait, a deadlock.
            assert (
                try_create_doc_permission_sync_attempt(
                    cc_pair_id, f"task-{uuid4().hex[:8]}", dispatch_session
                )
                is None
            )
        finally:
            dispatch_session.rollback()
            pause.result()

    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.CANCELED


def test_the_pause_does_not_wait_on_a_doc_sync_started_after_its_first_lock(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair_id = cc_pair.id
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())

    write_holds_lock = threading.Event()
    write_may_commit = threading.Event()
    started_attempt_id: int | None = None
    write: _CallOnItsOwnSession | None = None

    def sync_write(session: Session) -> None:
        assert started_attempt_id is not None
        lock_doc_permission_sync_attempt_if_owned(started_attempt_id, session)
        write_holds_lock.set()
        assert write_may_commit.wait(_WAIT_SECONDS)
        session.commit()

    lock_row = cc_pair_api.lock_connector_credential_pair_row

    # A sync is dispatched, claimed and writing after the pause's first lock
    def start_a_sync_then_lock(
        session: Session, pair_id: int
    ) -> ConnectorCredentialPair | None:
        nonlocal started_attempt_id, write
        with get_session_with_current_tenant() as sync_session:
            started_attempt_id = _running_doc_permission_sync(sync_session, pair_id)
        write = _CallOnItsOwnSession(sync_write)
        assert write_holds_lock.wait(_WAIT_SECONDS)
        return lock_row(session, pair_id)

    monkeypatch.setattr(
        cc_pair_api, "lock_connector_credential_pair_row", start_a_sync_then_lock
    )

    try:
        # Waiting under the pair lock for that write would stall the pause
        # until the write gives up
        _pause(db_session, cc_pair_id, admin)
    finally:
        db_session.rollback()
        write_may_commit.set()
        if write is not None:
            write.result()

    assert started_attempt_id is not None
    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, started_attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.IN_PROGRESS


@pytest.mark.parametrize(
    ("status", "status_after_pause"),
    [
        (PermissionSyncStatus.NOT_STARTED, PermissionSyncStatus.CANCELED),
        (PermissionSyncStatus.IN_PROGRESS, PermissionSyncStatus.IN_PROGRESS),
    ],
)
def test_pause_cancels_a_queued_group_sync_and_leaves_a_running_one_open(
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

    _pause(db_session, cc_pair.id, admin)

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
