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
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.build import tasks as tasks_module
from onyx.background.celery.tasks.build.tasks import cleanup_idle_sandboxes_task
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.sandbox.models import SnapshotResult
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_user

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
def _quiesce_leaked_sandboxes(db_session: Session) -> None:
    """Terminate RUNNING sandboxes leaked by earlier tests.

    The sweep covers ALL RUNNING sandboxes globally, so rows committed by
    other tests in this directory would otherwise leak into our assertions.
    """
    db_session.execute(
        update(Sandbox)
        .where(Sandbox.status == SandboxStatus.RUNNING)
        .values(status=SandboxStatus.TERMINATED)
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _isolated_redis_lock() -> Generator[None, None, None]:
    """Make sure the cleanup beat lock is free before + after each test.

    A leftover lock would cause the task to short-circuit at the
    ``lock.acquire`` step and silently skip the work we want to assert.
    """
    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
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
    stubbed_cleanup.supports_opencode_history_persistence = True
    stubbed_cleanup.create_opencode_history_snapshot_returns = True
    stubbed_cleanup.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{sandbox.id}/{session_row.id}.tar.gz",
        size_bytes=1234,
    )
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING

    # Scope assertions to THIS test's session: the cleanup task is tenant-wide,
    # so on a shared dev DB it may also sweep other sandboxes. Assert our
    # sandbox's outcome rather than global counts.
    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert len(snapshots) >= 1
    assert all(s.size_bytes == 1234 for s in snapshots)
    assert {
        "sandbox_id": sandbox.id,
        "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        "timeout_seconds": 300.0,
    } in stubbed_cleanup.create_opencode_history_snapshot_payloads
    assert stubbed_cleanup.terminate_count >= 1


def test_active_sandbox_within_threshold_not_touched(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,  # noqa: ARG001  (injects the stub manager)
    short_idle_threshold: int,
) -> None:
    """A sandbox whose heartbeat is fresher than the threshold is skipped."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)

    # Heartbeat half the threshold ago -> not idle.
    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold // 2)

    # Non-idle sandboxes still get the background-snapshot sweep; an empty
    # workspace listing makes it a no-op so we can assert "not touched".
    stubbed_cleanup.list_session_workspaces_returns = []

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    # Within threshold -> not swept -> stays RUNNING. (Global manager-call
    # counts aren't asserted: the task is tenant-wide and may process other
    # idle sandboxes on a shared dev DB.)
    assert refreshed.status == SandboxStatus.RUNNING


def test_null_heartbeat_sandbox_past_created_at_included(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
) -> None:
    """NULL heartbeat + ``created_at`` past threshold -> swept.

    Regression net for SHA ``eba89fa635`` — the OR-branch in
    the idle check that handles legacy rows / edge cases.
    """
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _backdate_created_at(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    stubbed_cleanup.list_session_workspaces_returns = []
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING
    assert stubbed_cleanup.terminate_count >= 1


def test_snapshot_failure_on_healthy_pod_aborts_sleep(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail-closed: a failing ``create_snapshot`` on a still-healthy pod must
    NOT terminate the sandbox. Terminating would lose the session's workspace
    (next restore would find no snapshot and fall back to a fresh template), so
    the sandbox stays RUNNING to be retried next cycle.
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

    monkeypatch.setattr(stubbed_cleanup, "create_snapshot", _boom)
    stubbed_cleanup.health_check_returns = True  # pod still reachable

    with caplog.at_level(logging.WARNING):
        cleanup_idle_sandboxes_task.run(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    # Fail-closed: THIS sandbox stays RUNNING — NOT terminated/SLEEPING. (The
    # task is tenant-wide; assert our sandbox's outcome, not global counts.)
    assert refreshed.status == SandboxStatus.RUNNING

    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert snapshots == []
    assert any("Failed to create snapshot" in r.getMessage() for r in caplog.records)


def test_opencode_history_snapshot_failure_on_healthy_pod_aborts_sleep(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail-closed before sleep if durable opencode history cannot be captured."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    stubbed_cleanup.supports_opencode_history_persistence = True
    stubbed_cleanup.health_check_returns = True

    def _boom(
        sandbox_id: object,
        _tenant_id: object,
    ) -> bool:
        stubbed_cleanup.create_opencode_history_snapshot_payloads.append(
            {
                "sandbox_id": sandbox_id,
                "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                "timeout_seconds": 300.0,
            }
        )
        raise RuntimeError("history store unreachable")

    monkeypatch.setattr(stubbed_cleanup, "create_opencode_history_snapshot", _boom)

    with caplog.at_level(logging.ERROR):
        cleanup_idle_sandboxes_task.run(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.RUNNING
    assert {"sandbox_id": sandbox.id} not in (
        stubbed_cleanup.list_session_workspaces_payloads
    )
    assert sandbox.id not in stubbed_cleanup.terminated_sandbox_ids
    assert {
        "sandbox_id": sandbox.id,
        "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        "timeout_seconds": 300.0,
    } in stubbed_cleanup.create_opencode_history_snapshot_payloads
    assert any(
        "opencode history snapshot failed" in r.getMessage() for r in caplog.records
    )


def test_opencode_history_snapshot_failure_on_unreachable_pod_still_terminates(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the pod is already unreachable, do not keep the sandbox RUNNING forever."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _backdate_heartbeat(db_session, sandbox, seconds_ago=short_idle_threshold * 4)

    stubbed_cleanup.supports_opencode_history_persistence = True
    stubbed_cleanup.health_check_returns = False
    stubbed_cleanup.list_session_workspaces_returns = []
    stubbed_cleanup.terminate_silent = True

    def _boom(
        sandbox_id: object,
        _tenant_id: object,
    ) -> bool:
        stubbed_cleanup.create_opencode_history_snapshot_payloads.append(
            {
                "sandbox_id": sandbox_id,
                "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                "timeout_seconds": 300.0,
            }
        )
        raise RuntimeError("pod gone")

    monkeypatch.setattr(stubbed_cleanup, "create_opencode_history_snapshot", _boom)

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.SLEEPING
    assert {
        "sandbox_id": sandbox.id
    } in stubbed_cleanup.list_session_workspaces_payloads
    assert sandbox.id in stubbed_cleanup.terminated_sandbox_ids


def test_snapshot_failure_on_unreachable_pod_still_terminates(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable pod is terminated despite the snapshot failure: its
    workspace is already gone, so keeping it RUNNING forever (never sleeping,
    never reclaimed) is worse than terminating.
    """
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    session_row = BuildSession(
        user_id=user.id,
        name="snapshot-fail-dead-pod",
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

    monkeypatch.setattr(stubbed_cleanup, "create_snapshot", _boom)
    stubbed_cleanup.health_check_returns = False  # pod unreachable
    stubbed_cleanup.terminate_silent = True

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    # Unreachable pod is terminated despite the snapshot failure. (Tenant-wide
    # task; assert our sandbox's outcome, not global counts.)
    assert refreshed.status == SandboxStatus.SLEEPING
    assert stubbed_cleanup.terminate_count >= 1


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

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    db_session.expire_all()
    refreshed_a = db_session.get(BuildSession, session_a.id)
    refreshed_b = db_session.get(BuildSession, session_b.id)
    assert refreshed_a is not None and refreshed_b is not None
    assert refreshed_a.status == BuildSessionStatus.IDLE
    assert refreshed_b.status == BuildSessionStatus.IDLE
    assert refreshed_a.nextjs_port is None
    assert refreshed_b.nextjs_port is None


def test_idle_reaped_before_non_idle_background_snapshot(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_cleanup: StubSandboxManager,
    short_idle_threshold: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single sweep reaps the idle sandbox (snapshot + terminate) before it
    background-snapshots a non-idle-but-stale one.

    ``get_running_sandboxes`` is forced to return the non-idle sandbox first,
    so a regression to interleaved processing would background-snapshot it
    before the idle one is reaped; idle-first partitioning must override that.
    """
    nonidle_user = make_user(db_session)
    nonidle_sandbox = make_sandbox(db_session, nonidle_user)
    nonidle_session = BuildSession(
        user_id=nonidle_user.id,
        name="nonidle-stale-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(nonidle_session)
    db_session.commit()
    db_session.refresh(nonidle_session)

    idle_user = make_user(db_session)
    idle_sandbox = make_sandbox(db_session, idle_user)
    idle_session = BuildSession(
        user_id=idle_user.id,
        name="idle-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(idle_session)
    db_session.commit()
    db_session.refresh(idle_session)

    # Idle: heartbeat well past the threshold. Non-idle: fresh heartbeat, but
    # its snapshot-less ACTIVE session defeats the staleness prefilter.
    _backdate_heartbeat(db_session, idle_sandbox, seconds_ago=short_idle_threshold * 4)
    _backdate_heartbeat(
        db_session, nonidle_sandbox, seconds_ago=short_idle_threshold // 2
    )

    def _list_workspaces(sandbox_id: UUID) -> list[UUID]:
        if sandbox_id == idle_sandbox.id:
            return [idle_session.id]
        if sandbox_id == nonidle_sandbox.id:
            return [nonidle_session.id]
        return []

    monkeypatch.setattr(stubbed_cleanup, "list_session_workspaces", _list_workspaces)

    # The sweep query has no ORDER BY, so force the adversarial order rather
    # than relying on physical row order matching commit order.
    real_get_running_sandboxes = tasks_module.get_running_sandboxes

    def _nonidle_first(session: Session) -> list[Sandbox]:
        return sorted(
            real_get_running_sandboxes(session),
            key=lambda s: s.id != nonidle_sandbox.id,
        )

    monkeypatch.setattr(tasks_module, "get_running_sandboxes", _nonidle_first)

    stubbed_cleanup.create_snapshot_returns = SnapshotResult(
        storage_path="s3://snapshots/ordering.tar.gz",
        size_bytes=1234,
    )
    stubbed_cleanup.terminate_silent = True

    # Record the (method, sandbox_id) sequence by wrapping the stub methods.
    call_log: list[tuple[str, UUID]] = []
    real_create_snapshot = stubbed_cleanup.create_snapshot
    real_terminate = stubbed_cleanup.terminate

    def _recording_create_snapshot(
        sandbox_id: UUID, session_id: UUID, tenant_id: str
    ) -> SnapshotResult | None:
        call_log.append(("create_snapshot", sandbox_id))
        return real_create_snapshot(sandbox_id, session_id, tenant_id)

    def _recording_terminate(sandbox_id: UUID) -> None:
        call_log.append(("terminate", sandbox_id))
        real_terminate(sandbox_id)

    monkeypatch.setattr(stubbed_cleanup, "create_snapshot", _recording_create_snapshot)
    monkeypatch.setattr(stubbed_cleanup, "terminate", _recording_terminate)

    cleanup_idle_sandboxes_task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    assert ("create_snapshot", idle_sandbox.id) in call_log, "idle never snapshotted"
    assert ("terminate", idle_sandbox.id) in call_log, "idle never terminated"
    assert (
        "create_snapshot",
        nonidle_sandbox.id,
    ) in call_log, "non-idle never background-snapshotted"
    idle_snapshot_idx = call_log.index(("create_snapshot", idle_sandbox.id))
    idle_terminate_idx = call_log.index(("terminate", idle_sandbox.id))
    nonidle_snapshot_idx = call_log.index(("create_snapshot", nonidle_sandbox.id))

    # The idle sandbox is fully reaped (snapshot, then terminate) before the
    # non-idle sandbox is background-snapshotted.
    assert idle_snapshot_idx < idle_terminate_idx < nonidle_snapshot_idx

    # The non-idle sandbox is never terminated.
    assert ("terminate", nonidle_sandbox.id) not in call_log

    db_session.expire_all()
    refreshed_idle = db_session.get(Sandbox, idle_sandbox.id)
    refreshed_nonidle = db_session.get(Sandbox, nonidle_sandbox.id)
    assert (
        refreshed_idle is not None and refreshed_idle.status == SandboxStatus.SLEEPING
    )
    assert (
        refreshed_nonidle is not None
        and refreshed_nonidle.status == SandboxStatus.RUNNING
    )


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
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        external_lock = redis_client.lock(
            OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
            timeout=60,
        )
        assert external_lock.acquire(blocking=False) is True

        try:
            cleanup_idle_sandboxes_task.run(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )

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
