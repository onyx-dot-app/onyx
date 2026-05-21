"""Idle cleanup (Celery task).

Exercises ``cleanup_idle_sandboxes_task`` end-to-end against real Postgres +
Redis. The sandbox operations (``list_session_workspaces``,
``create_snapshot``, ``terminate``) are routed through the
``StubSandboxManager`` from ``conftest.py``. The task body is
backend-agnostic, so we only need to install the stub via
``get_sandbox_manager``.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.tasks import tasks as tasks_module
from onyx.server.features.build.sandbox.tasks.tasks import cleanup_idle_sandboxes_task
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.stubs import StubSandboxManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stubbed_cleanup(
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> StubSandboxManager:
    """Wire the stub so the cleanup task runs entirely against it.

    The task body is backend-agnostic now: it calls
    ``sandbox_manager.list_session_workspaces(sandbox_id)`` rather than a
    Kubernetes-only helper, so we just need to redirect
    ``get_sandbox_manager`` to the stub. Per-test bodies can override
    ``stub.list_session_workspaces_returns`` to drive the snapshot loop.
    """
    monkeypatch.setattr(
        tasks_module, "get_sandbox_manager", lambda: stub_sandbox_manager
    )
    return stub_sandbox_manager


@pytest.fixture
def short_idle_threshold(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower the idle threshold so tests can backdate a heartbeat cheaply.

    Returns the threshold (seconds) so tests can reason about boundary
    conditions without hard-coding magic numbers.
    """
    threshold = 60
    monkeypatch.setattr(tasks_module, "SANDBOX_IDLE_TIMEOUT_SECONDS", threshold)
    return threshold


@pytest.fixture(autouse=True)
def _isolated_redis_lock() -> Generator[None, None, None]:
    """Make sure the cleanup beat lock is free before + after each test.

    A leftover lock would cause the task to short-circuit at the
    ``lock.acquire`` step and silently skip the work we want to assert.
    """
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    redis_client.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)
    try:
        yield
    finally:
        redis_client.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)


def _backdate_heartbeat(
    db_session: Session, sandbox: Sandbox, seconds_ago: int
) -> None:
    sandbox.last_heartbeat = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(seconds=seconds_ago)
    db_session.flush()
    db_session.commit()


def _backdate_created_at(
    db_session: Session, sandbox: Sandbox, seconds_ago: int
) -> None:
    sandbox.created_at = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(seconds=seconds_ago)
    sandbox.last_heartbeat = None
    db_session.flush()
    db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_idle_sandbox_snapshotted_then_terminated_then_sleep_status(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
) -> None:
    """Happy path: snapshot session, terminate pod, mark sandbox SLEEPING."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    session_row = BuildSession(
        user_id=user.id,
        name="idle-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)

    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    # Return our session id from the (stubbed) workspace listing so the
    # task tries to snapshot it.
    stubbed_cleanup.list_session_workspaces_returns = [session_row.id]
    stubbed_cleanup.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{sandbox.id}/{session_row.id}.tar.gz",
        size_bytes=1234,
    )
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING

    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert len(snapshots) == 1
    assert snapshots[0].size_bytes == 1234

    assert stubbed_cleanup.terminate_count == 1
    assert stubbed_cleanup.last_terminate_sandbox_id == sandbox.id


def test_active_sandbox_within_threshold_not_touched(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
) -> None:
    """A sandbox whose heartbeat is fresher than the threshold is skipped."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)

    # Heartbeat half the threshold ago -> not idle.
    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold // 2)

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.RUNNING

    # Manager APIs were never touched for this sandbox.
    assert stubbed_cleanup.terminate_count == 0
    assert stubbed_cleanup.create_snapshot_count == 0


def test_null_heartbeat_sandbox_past_created_at_included(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
) -> None:
    """NULL heartbeat + ``created_at`` past threshold -> swept.

    Regression net for SHA ``eba89fa635`` — the OR-branch in
    ``get_idle_sandboxes`` that handles legacy rows / edge cases.
    """
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _backdate_created_at(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    stubbed_cleanup.list_session_workspaces_returns = []
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING
    assert stubbed_cleanup.terminate_count == 1


def test_snapshot_failure_continues_to_termination(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing ``create_snapshot`` does not abort pod termination.

    The task body wraps the per-session snapshot in a ``try / except`` and
    logs at WARNING — terminate, idle-marking, and SLEEPING transitions
    must still happen so the pod doesn't leak.
    """
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    session_row = BuildSession(
        user_id=user.id,
        name="snapshot-fail-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)

    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    stubbed_cleanup.list_session_workspaces_returns = [session_row.id]

    def _boom(
        _sandbox_id: object, _session_id: object, _tenant_id: object
    ) -> SnapshotResult:
        raise RuntimeError("S3 unreachable")

    # Override the method so the failure path is exercised (the stub's
    # default still records the call counts via attribute access).
    monkeypatch.setattr(stubbed_cleanup, "create_snapshot", _boom)
    stubbed_cleanup.terminate_silent = True

    with caplog.at_level(logging.WARNING):
        cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING

    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert snapshots == []
    assert stubbed_cleanup.terminate_count == 1
    assert any("Failed to create snapshot" in r.getMessage() for r in caplog.records)


def test_sessions_marked_idle_and_nextjs_ports_cleared(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
) -> None:
    """All ACTIVE sessions for the user flip to IDLE; ``nextjs_port`` cleared."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)

    session_a = BuildSession(
        user_id=user.id,
        name="session-a",
        status=BuildSessionStatus.ACTIVE,
        nextjs_port=3010,
    )
    session_b = BuildSession(
        user_id=user.id,
        name="session-b",
        status=BuildSessionStatus.ACTIVE,
        nextjs_port=3011,
    )
    db_session.add_all([session_a, session_b])
    db_session.commit()
    db_session.refresh(session_a)
    db_session.refresh(session_b)

    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)
    stubbed_cleanup.list_session_workspaces_returns = []
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    refreshed_a = db_session.get(BuildSession, session_a.id)
    refreshed_b = db_session.get(BuildSession, session_b.id)
    assert refreshed_a is not None and refreshed_b is not None
    assert refreshed_a.status == BuildSessionStatus.IDLE
    assert refreshed_b.status == BuildSessionStatus.IDLE
    assert refreshed_a.nextjs_port is None
    assert refreshed_b.nextjs_port is None


def test_task_holds_redis_lock_for_duration(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,  # noqa: ARG001
    short_idle_threshold: int,
) -> None:
    """A concurrent invocation observes the beat lock and bails out.

    We pre-acquire the lock from outside the task — exactly the situation
    a second beat tick would face — then verify the task short-circuits
    (no terminate, no DB mutation) and that the lock is still held after
    the task returns (so the outside owner can release it cleanly).
    """
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    # Bind tenant context for the redis client lookup.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        external_lock = redis_client.lock(
            OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
            timeout=60,
        )
        assert external_lock.acquire(blocking=False) is True

        try:
            cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

            # Task must have bailed without doing any work.
            assert stubbed_cleanup.terminate_count == 0
            assert stubbed_cleanup.create_snapshot_count == 0

            db_session.expire_all()
            refreshed = db_session.get(Sandbox, sandbox.id)
            assert refreshed is not None
            assert refreshed.status == SandboxStatus.RUNNING

            # The lock is still owned by the outside holder — the task did
            # not steal or release it.
            assert external_lock.owned() is True
        finally:
            external_lock.release()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
