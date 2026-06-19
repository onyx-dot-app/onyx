"""Background snapshot behavior of the sandbox sweep (Celery task).

Exercises the snapshot half of ``cleanup_idle_sandboxes_task`` — non-idle
RUNNING sandboxes get their changed sessions snapshotted in place — end-to-end
against real Postgres + Redis. Sandbox operations (``list_session_workspaces``,
``create_snapshot``) are routed through the ``StubSandboxManager`` from
``conftest.py``.

For sandboxes that are NOT idle, the sweep must never terminate pods or
change sandbox/session status — it only bounds data loss from ungraceful pod
death (kubelet eviction, node loss). The reap half is covered by
``test_idle_cleanup.py``.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

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
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.stubs import StubSandboxManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeSnapshotManager:
    """Records blob deletes instead of hitting the real file store."""

    def __init__(self) -> None:
        self.deleted_paths: list[str] = []

    def delete_snapshot(self, storage_path: str) -> None:
        self.deleted_paths.append(storage_path)


@pytest.fixture
def fake_snapshot_manager(monkeypatch: pytest.MonkeyPatch) -> _FakeSnapshotManager:
    fake = _FakeSnapshotManager()
    monkeypatch.setattr(tasks_module, "SnapshotManager", lambda _file_store: fake)
    monkeypatch.setattr(tasks_module, "get_default_file_store", lambda: None)
    return fake


@pytest.fixture
def stubbed_sweep(
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> StubSandboxManager:
    """Wire the stub so the sweep runs entirely against it."""
    monkeypatch.setattr(
        tasks_module, "get_sandbox_manager", lambda: stub_sandbox_manager
    )
    return stub_sandbox_manager


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
    """Make sure the sweep beat lock is free before + after."""
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    redis_client.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)
    try:
        yield
    finally:
        redis_client.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)


def _make_session(db_session: Session, user: User) -> BuildSession:
    session_row = BuildSession(
        user_id=user.id,
        name="background-snapshot-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)
    return session_row


def _add_snapshot(
    db_session: Session,
    session_id: UUID,
    *,
    age_seconds: int,
) -> Snapshot:
    """Insert a snapshot row backdated by ``age_seconds``."""
    snapshot = Snapshot(
        session_id=session_id,
        storage_path=f"sandbox-snapshots/test/{uuid4()}.tar.gz",
        size_bytes=100,
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.execute(
        update(Snapshot)
        .where(Snapshot.id == snapshot.id)
        .values(
            created_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=age_seconds)
        )
    )
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_running_sandbox_snapshotted_without_termination(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
) -> None:
    """Happy path: snapshot is recorded; pod and statuses are untouched."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    session_row = _make_session(db_session, user)
    db_session.commit()

    stubbed_sweep.list_session_workspaces_returns = [session_row.id]
    stubbed_sweep.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{sandbox.id}/{uuid4()}.tar.gz",
        size_bytes=4321,
    )

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert len(snapshots) == 1
    assert snapshots[0].size_bytes == 4321

    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.status == SandboxStatus.RUNNING
    refreshed_session = db_session.get(BuildSession, session_row.id)
    assert refreshed_session is not None
    assert refreshed_session.status == BuildSessionStatus.ACTIVE
    assert stubbed_sweep.terminate_count == 0


def test_fresh_snapshot_skipped_by_age_gate(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
) -> None:
    """Sessions whose latest snapshot is newer than the interval are skipped
    without any pod traffic — the DB prefilter even skips the workspace
    listing exec."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    session_row = _make_session(db_session, user)
    _add_snapshot(db_session, session_row.id, age_seconds=10)

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    assert stubbed_sweep.list_session_workspaces_count == 0
    assert stubbed_sweep.create_snapshot_count == 0


def test_stale_session_defeats_prefilter(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
) -> None:
    """One stale session among fresh ones is enough to reach the pod."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    fresh = _make_session(db_session, user)
    stale = _make_session(db_session, user)
    _add_snapshot(db_session, fresh.id, age_seconds=10)
    interval = (
        tasks_module.SANDBOX_IDLE_TIMEOUT_SECONDS
        // tasks_module.SNAPSHOT_INTERVAL_DIVISOR
    )
    _add_snapshot(db_session, stale.id, age_seconds=interval * 2)

    stubbed_sweep.list_session_workspaces_returns = [fresh.id, stale.id]
    stubbed_sweep.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{uuid4()}.tar.gz",
        size_bytes=55,
    )

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    assert stubbed_sweep.list_session_workspaces_count == 1
    # The per-session age gate still protects the fresh session.
    assert stubbed_sweep.create_snapshot_count == 1
    assert stubbed_sweep.last_create_snapshot_payload is not None
    assert stubbed_sweep.last_create_snapshot_payload["session_id"] == stale.id


def test_stale_snapshot_resnapshotted_and_priors_pruned(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
    fake_snapshot_manager: _FakeSnapshotManager,
) -> None:
    """A stale session is re-snapshotted; prune-on-write keeps only the
    latest (prior blob deleted first, then its row)."""
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    session_row = _make_session(db_session, user)

    interval = (
        tasks_module.SANDBOX_IDLE_TIMEOUT_SECONDS
        // tasks_module.SNAPSHOT_INTERVAL_DIVISOR
    )
    prior = _add_snapshot(db_session, session_row.id, age_seconds=interval * 2)
    prior_path = prior.storage_path

    stubbed_sweep.list_session_workspaces_returns = [session_row.id]
    stubbed_sweep.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{sandbox.id}/{uuid4()}.tar.gz",
        size_bytes=999,
    )

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    assert stubbed_sweep.create_snapshot_count == 1
    db_session.expire_all()
    snapshots = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).all()
    )
    assert len(snapshots) == 1
    assert snapshots[0].size_bytes == 999
    assert fake_snapshot_manager.deleted_paths == [prior_path]


def test_snapshot_failure_continues_other_sessions(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing ``create_snapshot`` is logged and the sweep continues."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    session_a = _make_session(db_session, user)
    session_b = _make_session(db_session, user)

    stubbed_sweep.list_session_workspaces_returns = [session_a.id, session_b.id]

    real_result = SnapshotResult(
        storage_path=f"s3://snapshots/{uuid4()}.tar.gz", size_bytes=55
    )

    def _snapshot(
        _sandbox_id: object, session_id: object, _tenant_id: object
    ) -> SnapshotResult:
        if session_id == session_a.id:
            raise RuntimeError("FileStore unreachable")
        return real_result

    monkeypatch.setattr(stubbed_sweep, "create_snapshot", _snapshot)

    with caplog.at_level(logging.WARNING):
        cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    db_session.expire_all()
    snapshots_a = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_a.id).all()
    )
    snapshots_b = (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_b.id).all()
    )
    assert snapshots_a == []
    assert len(snapshots_b) == 1
    assert any("Failed to create snapshot" in r.getMessage() for r in caplog.records)


def test_no_running_sandboxes_is_a_noop(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_sweep: StubSandboxManager,
) -> None:
    """SLEEPING sandboxes are never swept."""
    user = make_user(db_session)
    make_sandbox(db_session, user, status=SandboxStatus.SLEEPING)
    db_session.commit()

    cleanup_idle_sandboxes_task.run(tenant_id=TEST_TENANT_ID)

    assert stubbed_sweep.list_session_workspaces_count == 0
    assert stubbed_sweep.create_snapshot_count == 0
