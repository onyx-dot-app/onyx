"""Runtime reconciliation (Celery task).

Exercises ``reconcile_sandbox_runtimes_task`` against real Postgres + Redis.
The reconciler starts from the runtimes the sandbox manager reports, so it
reaches tenants whether or not the per-tenant fanout runs for them. Runtime
operations go through ``StubSandboxManager``.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.build import tasks as tasks_module
from onyx.background.celery.tasks.build.tasks import reconcile_sandbox_runtimes_task
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.db.models import BuildSession, Sandbox, Snapshot, User
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
    SnapshotResult,
)
from onyx.server.features.build.session import (
    sandbox_lifecycle as sandbox_lifecycle_module,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
IDLE_TIMEOUT_SECONDS = 60


@pytest.fixture
def stub(
    stub_sandbox_manager: StubSandboxManager, monkeypatch: pytest.MonkeyPatch
) -> StubSandboxManager:
    monkeypatch.setattr(
        tasks_module, "get_sandbox_manager", lambda: stub_sandbox_manager
    )
    monkeypatch.setattr(
        tasks_module, "SANDBOX_IDLE_TIMEOUT_SECONDS", IDLE_TIMEOUT_SECONDS
    )
    monkeypatch.setattr(
        sandbox_lifecycle_module, "SANDBOX_IDLE_TIMEOUT_SECONDS", IDLE_TIMEOUT_SECONDS
    )
    stub_sandbox_manager.resources_returns = []
    stub_sandbox_manager.terminate_silent = True
    return stub_sandbox_manager


@pytest.fixture(autouse=True)
def _quiesce_leaked_sandboxes(db_session: Session) -> None:
    """The sweep covers every RUNNING row; retire rows leaked by other tests."""
    db_session.execute(
        update(Sandbox)
        .where(Sandbox.status == SandboxStatus.RUNNING)
        .values(status=SandboxStatus.TERMINATED)
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _free_sweep_lock() -> Generator[None, None, None]:
    cache = get_cache_backend(tenant_id=TENANT_ID)
    cache.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)
    cache.delete(tasks_module.RUNNING_SANDBOX_CURSOR_KEY)
    try:
        yield
    finally:
        cache.delete(OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK)
        cache.delete(tasks_module.RUNNING_SANDBOX_CURSOR_KEY)


def _runtime(
    sandbox_id: UUID,
    *,
    tenant_id: str = TENANT_ID,
    attempt: int = 0,
    age_seconds: int = 2 * 60 * 60,
    legacy: bool = False,
) -> SandboxResource:
    return SandboxResource(
        kind=SandboxResourceKind.POD,
        name=f"sandbox-{str(sandbox_id)[:8]}",
        instance_id=f"uid-{sandbox_id}",
        sandbox_id=sandbox_id,
        tenant_id=tenant_id,
        created_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=age_seconds),
        provisioning_attempt_number=attempt,
        legacy_ownership=legacy,
    )


def _sandbox(
    db_session: Session,
    *,
    status: SandboxStatus = SandboxStatus.RUNNING,
    heartbeat_seconds_ago: int = 0,
    attempt: int = 0,
) -> Sandbox:
    sandbox = make_sandbox(db_session, make_user(db_session), status=status)
    sandbox.provisioning_attempt_number = attempt
    sandbox.last_heartbeat = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(seconds=heartbeat_seconds_ago)
    db_session.commit()
    return sandbox


def _status(db_session: Session, sandbox_id: UUID) -> SandboxStatus:
    db_session.expire_all()
    sandbox = db_session.get(Sandbox, sandbox_id)
    assert sandbox is not None
    return sandbox.status


def test_idle_runtime_is_snapshotted_and_slept_without_the_tenant_fanout(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    """A tenant the fanout skips, such as a gated one, still has its idle
    runtime snapshotted and slept."""
    sandbox = _sandbox(db_session, heartbeat_seconds_ago=IDLE_TIMEOUT_SECONDS * 4)
    session_row = BuildSession(
        user_id=sandbox.user_id, name="idle", status=BuildSessionStatus.ACTIVE
    )
    db_session.add(session_row)
    db_session.commit()
    stub.resources_returns = [_runtime(sandbox.id)]
    stub.list_session_workspaces_returns = [session_row.id]
    stub.create_snapshot_returns = SnapshotResult(
        storage_path=f"s3://snapshots/{sandbox.id}/{session_row.id}.tar.gz",
        size_bytes=1234,
    )

    reconcile_sandbox_runtimes_task.run()

    assert _status(db_session, sandbox.id) == SandboxStatus.SLEEPING
    assert (
        db_session.query(Snapshot).filter(Snapshot.session_id == session_row.id).count()
        >= 1
    )
    assert stub.terminate_count >= 1


def test_active_owned_runtime_is_untouched(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    sandbox = _sandbox(db_session, heartbeat_seconds_ago=0)
    runtime = _runtime(sandbox.id)
    stub.resources_returns = [runtime]

    reconcile_sandbox_runtimes_task.run()

    assert _status(db_session, sandbox.id) == SandboxStatus.RUNNING
    assert stub.deleted_resources == []
    assert stub.terminate_count == 0


@pytest.mark.parametrize(
    ("age_seconds", "legacy", "deleted"),
    [
        (2 * 60 * 60, False, True),
        (0, False, False),
        (2 * 60 * 60, True, False),
    ],
    ids=["past-grace", "within-grace", "legacy"],
)
def test_runtime_without_a_row(
    age_seconds: int,
    legacy: bool,
    deleted: bool,
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    owner = _sandbox(db_session, status=SandboxStatus.TERMINATED)
    db_session.delete(owner)
    db_session.commit()
    runtime = _runtime(owner.id, age_seconds=age_seconds, legacy=legacy)
    stub.resources_returns = [runtime]

    reconcile_sandbox_runtimes_task.run()

    assert stub.deleted_resources == ([runtime] if deleted else [])


@pytest.mark.parametrize(
    ("row_attempt", "runtime_attempt", "deleted"),
    [(2, 1, True), (2, 2, True), (2, 3, False)],
    ids=["older-attempt", "same-attempt", "newer-attempt"],
)
def test_runtime_of_a_sleeping_row(
    row_attempt: int,
    runtime_attempt: int,
    deleted: bool,
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    sandbox = _sandbox(db_session, status=SandboxStatus.SLEEPING, attempt=row_attempt)
    runtime = _runtime(sandbox.id, attempt=runtime_attempt)
    stub.resources_returns = [runtime]

    reconcile_sandbox_runtimes_task.run()

    assert stub.deleted_resources == ([runtime] if deleted else [])


def test_foreign_tenant_runtime_is_retained_in_single_tenant_mode(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    owner = _sandbox(db_session, status=SandboxStatus.TERMINATED)
    runtime = _runtime(owner.id, tenant_id="another-deployment-tenant")
    stub.resources_returns = [runtime]

    reconcile_sandbox_runtimes_task.run()

    assert stub.deleted_resources == []


def test_held_sweep_lock_skips_the_tenant_for_this_run(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub: StubSandboxManager,
) -> None:
    idle = _sandbox(db_session, heartbeat_seconds_ago=IDLE_TIMEOUT_SECONDS * 4)
    orphan = _sandbox(db_session, status=SandboxStatus.TERMINATED)
    stub.resources_returns = [_runtime(idle.id), _runtime(orphan.id)]
    lock = get_cache_backend(tenant_id=TENANT_ID).lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK, timeout=60
    )
    assert lock.acquire(blocking=False)
    try:
        reconcile_sandbox_runtimes_task.run()
    finally:
        lock.release()

    assert _status(db_session, idle.id) == SandboxStatus.RUNNING
    assert stub.deleted_resources == []
    assert stub.terminate_count == 0
