import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheLockLostError
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    SandboxCleanupCheckpoint,
    SandboxResource,
    SandboxResourceKind,
)
from onyx.server.features.build.session import resource_cleanup as cleanup
from onyx.server.features.build.session import sandbox_lifecycle as lifecycle
from onyx.server.features.build.timeouts import (
    BULK_TRANSFER_TIMEOUT_SECONDS,
    PROVISION_DEADLINE_SECONDS,
    SESSION_FLOW_LOCK_LEASE_SECONDS,
)


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    manager = MagicMock(spec=SandboxManager)
    manager.workspace_storage_identity.return_value = "workspace-v1"
    cache = MagicMock()
    cache.get.return_value = None
    monkeypatch.setattr(cleanup, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(cleanup, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(cleanup, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(cleanup, "get_stale_provisioning_sandboxes", lambda *_args: [])
    monkeypatch.setattr(
        cleanup, "record_cleanup_checkpoint__no_commit", MagicMock(return_value=True)
    )
    return manager, cache


def _resource(**updates: object) -> SandboxResource:
    values: dict[str, object] = {
        "sandbox_id": uuid4(),
        "tenant_id": "tenant-a",
        "kind": SandboxResourceKind.POD,
        "name": "sandbox-12345678",
        "instance_id": "old-uid",
        "provisioning_attempt_number": 1,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    values.update(updates)
    return SandboxResource.model_validate(values)


def test_checkpoint_locks_survive_three_full_bulk_transfers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = 0.0
    expires_at = PROVISION_DEADLINE_SECONDS
    session_expires_at = SESSION_FLOW_LOCK_LEASE_SECONDS
    claim = MagicMock()
    claim.owned.side_effect = lambda: elapsed < expires_at

    def renew(ttl: float) -> None:
        nonlocal expires_at
        expires_at = elapsed + ttl

    def snapshot(*_args: object) -> None:
        nonlocal elapsed
        elapsed += BULK_TRANSFER_TIMEOUT_SECONDS

    claim.extend.side_effect = renew
    session_lock = MagicMock()
    session_lock.owned.side_effect = lambda: elapsed < session_expires_at

    def renew_session(ttl: float, *, replace_ttl: bool) -> None:
        nonlocal session_expires_at
        assert replace_ttl
        assert session_lock.owned()
        session_expires_at = elapsed + ttl

    session_lock.extend.side_effect = renew_session
    session_context = MagicMock()
    session_context.__enter__.return_value = session_lock
    manager = MagicMock(spec=SandboxManager)
    manager.supports_opencode_history_persistence = False
    manager.workspace_storage_exists.return_value = True
    manager.list_session_workspaces.return_value = [uuid4(), uuid4(), uuid4()]
    monkeypatch.setattr(
        cleanup, "session_creation_lock", lambda _user_id: session_context
    )
    monkeypatch.setattr(cleanup, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(cleanup, "get_orphan_build_session_ids", lambda *_args: set())
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)

    cleanup._checkpoint_failed_runtime(
        manager,
        uuid4(),
        uuid4(),
        "tenant-a",
        lambda: cleanup._check_resource_claim(claim, lambda: None),
    )

    assert claim.owned()
    assert session_lock.owned()
    assert elapsed == 3 * BULK_TRANSFER_TIMEOUT_SECONDS
    assert elapsed > SESSION_FLOW_LOCK_LEASE_SECONDS


@pytest.mark.parametrize(
    "stage", ["entry", "history", "listing", "snapshot", "final_snapshot"]
)
def test_lost_checkpoint_session_lock_cannot_save_proof_or_delete(
    stage: str,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    volume = _resource(
        kind=SandboxResourceKind.VOLUME, provisioning_attempt_number=None
    )
    row = Sandbox(
        id=volume.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=2,
    )
    manager.iter_resources.side_effect = lambda *_args: iter([volume])
    manager.supports_opencode_history_persistence = True
    manager.workspace_storage_exists.return_value = True
    session_lock = MagicMock()
    session_lock.owned.return_value = stage != "entry"
    context = MagicMock()
    context.__enter__.return_value = session_lock
    monkeypatch.setattr(cleanup, "session_creation_lock", lambda _user_id: context)
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    monkeypatch.setattr(cleanup, "get_orphan_build_session_ids", lambda *_args: set())
    proof = MagicMock(return_value=True)
    monkeypatch.setattr(cleanup, "record_cleanup_checkpoint__no_commit", proof)

    def history(*_args: object) -> None:
        if stage == "history":
            session_lock.owned.return_value = False

    def list_workspaces(*_args: object) -> list[UUID]:
        if stage == "listing":
            session_lock.owned.return_value = False
        return [uuid4(), uuid4()]

    snapshot = MagicMock()

    def save_snapshot(*_args: object) -> None:
        if stage == "snapshot" or (
            stage == "final_snapshot" and snapshot.call_count == 2
        ):
            session_lock.owned.return_value = False

    manager.create_opencode_history_snapshot.side_effect = history
    manager.list_session_workspaces.side_effect = list_workspaces
    snapshot.side_effect = save_snapshot
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)

    with pytest.raises(CacheLockLostError, match="checkpoint session lock lost"):
        cleanup.reconcile_sandbox_resources(
            manager, "tenant-a", time.monotonic() + 60, lambda: None
        )

    proof.assert_not_called()
    manager.delete_resource.assert_not_called()
    assert snapshot.call_count == (
        2 if stage == "final_snapshot" else int(stage == "snapshot")
    )


@pytest.mark.parametrize(
    "status",
    [None, SandboxStatus.FAILED, SandboxStatus.SLEEPING, SandboxStatus.TERMINATED],
)
def test_collects_orphans_and_failed_or_inactive_runtime_resources(
    status: SandboxStatus | None,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    manager.iter_resources.return_value = iter([resource])
    row = (
        None
        if status is None
        else Sandbox(
            id=resource.sandbox_id,
            user_id=uuid4(),
            status=status,
            provisioning_attempt_number=1,
        )
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_args.args[0] == resource


@pytest.mark.parametrize("status", [SandboxStatus.RUNNING, SandboxStatus.PROVISIONING])
def test_preserves_live_or_provisioning_owners(
    status: SandboxStatus,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    manager.iter_resources.return_value = iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=status,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


def test_db_read_failure_does_not_authorize_orphan_deletion(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    monkeypatch.setattr(
        cleanup,
        "get_sandbox_by_id",
        MagicMock(side_effect=RuntimeError("DB unavailable")),
    )
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


@pytest.mark.parametrize(
    ("updates", "should_delete"),
    [
        ({}, True),
        ({"tenant_id": "tenant-b"}, False),
        ({"created_at": datetime.now(timezone.utc)}, False),
        ({"provisioning_attempt_number": 2}, False),
    ],
)
def test_collection_respects_tenant_age_and_generation(
    updates: dict[str, object],
    should_delete: bool,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource(**updates)
    manager.iter_resources.return_value = iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.SLEEPING,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    if should_delete:
        assert manager.delete_resource.call_args.args[0] == resource
    else:
        manager.delete_resource.assert_not_called()


@pytest.mark.parametrize("idle", [True, False])
@pytest.mark.parametrize("lease_owned", [True, False])
def test_inventory_failure_preserves_existing_sweep_only_while_lease_owned(
    idle: bool,
    lease_owned: bool,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.background.celery.tasks.build import tasks
    from onyx.server.features.build.session import sandbox_lifecycle as lifecycle

    manager, cache = collector
    manager.supports_opencode_history_persistence = False
    sandbox = Sandbox(id=uuid4(), user_id=uuid4(), status=SandboxStatus.RUNNING)
    session_id = uuid4()

    def broken_inventory(*_args: object) -> Iterator[SandboxResource]:
        yield _resource()
        raise RuntimeError("Inventory unavailable")

    manager.iter_resources.side_effect = broken_inventory
    redis = MagicMock()
    redis.lock.return_value.owned.return_value = lease_owned
    cache.lock.return_value.owned.return_value = lease_owned
    cache.get.return_value = None
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    monkeypatch.setattr(tasks, "get_redis_client", lambda **_kwargs: redis)
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(tasks, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(
        tasks, "get_running_sandboxes", MagicMock(side_effect=[[sandbox], []])
    )
    monkeypatch.setattr(tasks, "maybe_mark_tenant_active", MagicMock())
    monkeypatch.setattr(tasks, "user_has_stale_active_session", lambda *_args: True)
    monkeypatch.setattr(tasks, "get_latest_snapshot_for_session", lambda *_args: None)
    monkeypatch.setattr(lifecycle, "is_sandbox_idle", lambda *_args: idle)
    monkeypatch.setattr(
        lifecycle, "list_snapshotable_session_workspaces", lambda *_args: [session_id]
    )
    sleep = MagicMock()
    snapshot = MagicMock(return_value=None)
    monkeypatch.setattr(lifecycle, "sleep_sandbox", sleep)
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)

    if not lease_owned:
        with pytest.raises(CacheLockLostError, match="Sandbox cleanup lease lost"):
            tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]
        sleep.assert_not_called()
        snapshot.assert_not_called()
        return

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]
    if idle:
        assert sleep.call_args.kwargs["sandbox"].id == sandbox.id
        snapshot.assert_not_called()
    else:
        assert snapshot.call_args.kwargs["session_id"] == session_id
        sleep.assert_not_called()


def test_deletion_failure_does_not_skip_other_resources(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, cache = collector
    resources = [_resource(kind=SandboxResourceKind.SERVICE), _resource()]
    manager.iter_resources.return_value = iter(resources)
    manager.delete_resource.side_effect = [
        RuntimeError("Service deletion failed"),
        None,
    ]
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_count == 2
    cache.set.assert_called_once()


def test_expires_stale_provisioning_without_any_runtime_resources(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter(())
    row = Sandbox(id=uuid4(), user_id=uuid4(), provisioning_attempt_number=3)
    monkeypatch.setattr(
        cleanup, "get_stale_provisioning_sandboxes", lambda *_args: [row]
    )
    expire = MagicMock()
    monkeypatch.setattr(cleanup, "fail_stale_provisioning__no_commit", expire)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert expire.call_args.args[1:3] == (row.id, 3)


def test_lost_claim_stops_deletion(
    collector: tuple[MagicMock, MagicMock],
    runtime_lock_cache: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    runtime_lock_cache.lock.return_value.owned.return_value = False
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


@pytest.mark.parametrize("snapshot_fails", [True, False])
def test_prior_runtime_work_requires_checkpoint_before_collection(
    snapshot_fails: bool,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    resources = [
        resource,
        _resource(
            sandbox_id=resource.sandbox_id,
            kind=SandboxResourceKind.SERVICE,
            provisioning_attempt_number=None,
        ),
    ]
    manager.iter_resources.side_effect = lambda *_args: iter(resources)
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=2,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    checkpoint = MagicMock(
        side_effect=RuntimeError("checkpoint failed") if snapshot_fails else None
    )
    monkeypatch.setattr(cleanup, "_checkpoint_failed_runtime", checkpoint)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert checkpoint.called
    assert manager.delete_resource.call_count == (0 if snapshot_fails else 2)


def test_new_attempt_failure_does_not_require_checkpoint_of_restored_files(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    manager.iter_resources.side_effect = lambda *_args: iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    checkpoint = MagicMock()
    monkeypatch.setattr(cleanup, "_checkpoint_failed_runtime", checkpoint)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    checkpoint.assert_not_called()
    manager.delete_resource.assert_called_once()


def test_new_container_cannot_skip_checkpoint_for_a_retained_workspace_volume(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    container = _resource(
        kind=SandboxResourceKind.CONTAINER, provisioning_attempt_number=2
    )
    volume = _resource(
        kind=SandboxResourceKind.VOLUME,
        sandbox_id=container.sandbox_id,
        provisioning_attempt_number=None,
    )
    manager.iter_resources.side_effect = lambda *_args: iter([container, volume])
    row = Sandbox(
        id=container.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=2,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    checkpoint = MagicMock(side_effect=RuntimeError("Cannot checkpoint retained files"))
    monkeypatch.setattr(cleanup, "_checkpoint_failed_runtime", checkpoint)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert checkpoint.called
    manager.delete_resource.assert_not_called()


@pytest.mark.parametrize("change", [None, "heartbeat", "attempt", "storage"])
def test_failed_collector_retries_only_with_current_proof_after_runtime_deletion(
    change: str | None,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    container = _resource(kind=SandboxResourceKind.CONTAINER)
    volume = _resource(
        sandbox_id=container.sandbox_id,
        kind=SandboxResourceKind.VOLUME,
        provisioning_attempt_number=None,
    )
    resources = [container, volume]
    row = Sandbox(
        id=container.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=2,
    )
    manager.supports_opencode_history_persistence = False
    manager.iter_resources.side_effect = lambda *_args: iter(list(resources))
    manager.runtime_exists.side_effect = lambda *_args: container in resources
    manager.workspace_storage_exists.return_value = True

    def list_workspaces(_sandbox_id: object) -> list[UUID]:
        if container not in resources:
            raise RuntimeError("Workspace discovery needs the runtime")
        return [uuid4()]

    manager.list_session_workspaces.side_effect = list_workspaces
    db_session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = db_session
    monkeypatch.setattr(cleanup, "get_session_with_current_tenant", lambda: context)
    monkeypatch.setattr(cleanup, "session_creation_lock", MagicMock())
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    monkeypatch.setattr(cleanup, "get_orphan_build_session_ids", lambda *_args: set())
    snapshot = MagicMock()
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)

    def record(
        _db_session: object,
        _sandbox_id: object,
        proof: SandboxCleanupCheckpoint,
        *,
        expected_status: SandboxStatus,
    ) -> bool:
        assert expected_status == SandboxStatus.FAILED
        row.cleanup_checkpoint = proof.model_dump(mode="json")
        return True

    monkeypatch.setattr(cleanup, "record_cleanup_checkpoint__no_commit", record)
    volume_attempts = 0

    def delete(resource: SandboxResource, _deadline: float) -> None:
        nonlocal volume_attempts
        assert row.cleanup_checkpoint is not None
        db_session.commit.assert_called_once()
        if resource == volume:
            volume_attempts += 1
            if volume_attempts == 1:
                raise RuntimeError("Volume busy")
        resources.remove(resource)
        if resource == container:
            if change == "heartbeat":
                row.last_heartbeat = datetime.now(timezone.utc)
            elif change == "attempt":
                row.provisioning_attempt_number += 1
            elif change == "storage":
                manager.workspace_storage_identity.return_value = "replacement-volume"

    manager.delete_resource.side_effect = delete
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert resources == [volume]
    assert snapshot.call_count == 1

    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert resources == ([] if change is None else [volume])
    assert snapshot.call_count == 1
    assert volume_attempts == (2 if change is None else 0)


@pytest.mark.parametrize(
    "mismatch", [None, "runtime", "attempt", "heartbeat", "storage"]
)
def test_failed_checkpoint_reuse_requires_matching_proof_and_no_runtime(
    mismatch: str | None,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    volume = _resource(
        kind=SandboxResourceKind.VOLUME, provisioning_attempt_number=None
    )
    heartbeat = datetime.now(timezone.utc) - timedelta(hours=1)
    row = Sandbox(
        id=volume.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=2,
        last_heartbeat=heartbeat,
        cleanup_checkpoint=SandboxCleanupCheckpoint(
            provisioning_attempt_number=1 if mismatch == "attempt" else 2,
            storage_identity="old-volume" if mismatch == "storage" else "workspace-v1",
            last_heartbeat=None if mismatch == "heartbeat" else heartbeat,
        ).model_dump(mode="json"),
    )
    manager.iter_resources.side_effect = lambda *_args: iter([volume])
    manager.runtime_exists.return_value = mismatch == "runtime"
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    monkeypatch.setattr(cleanup, "user_has_build_sessions", lambda *_args: True)
    checkpoint = MagicMock(side_effect=RuntimeError("Fresh checkpoint required"))
    monkeypatch.setattr(cleanup, "_checkpoint_failed_runtime", checkpoint)

    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )

    if mismatch is None:
        checkpoint.assert_not_called()
        manager.delete_resource.assert_called_once()
    else:
        checkpoint.assert_called_once()
        manager.delete_resource.assert_not_called()


@pytest.mark.parametrize("has_db_owner", [True, False])
def test_legacy_secret_needs_verified_tenant_ownership(
    has_db_owner: bool,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource(kind=SandboxResourceKind.SECRET, legacy_ownership=True)
    manager.iter_resources.return_value = iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.TERMINATED,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(
        cleanup, "get_sandbox_by_id", lambda *_args: row if has_db_owner else None
    )
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_count == int(has_db_owner)


def test_task_collects_orphans_with_no_running_database_rows(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.background.celery.tasks.build import tasks

    manager, cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(tasks, "get_redis_client", MagicMock())
    monkeypatch.setattr(tasks, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(tasks, "get_running_sandboxes", lambda *_args, **_kwargs: [])
    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]
    manager.delete_resource.assert_called_once()


def test_deletion_batch_is_bounded(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter(
        [_resource(instance_id=f"uid-{i}") for i in range(120)]
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_count == cleanup.MAX_CLEANUP_RESOURCES


def test_mismatched_tenant_context_stops_inventory(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    monkeypatch.setattr(cleanup, "get_current_tenant_id", lambda: "tenant-b")
    with pytest.raises(RuntimeError, match="tenant context mismatch"):
        cleanup.reconcile_sandbox_resources(
            manager, "tenant-a", time.monotonic() + 60, lambda: None
        )
    manager.iter_resources.assert_not_called()
    manager.delete_resource.assert_not_called()


def test_cleanup_lease_loss_on_last_resource_aborts_without_retry(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    check_ownership = MagicMock(
        side_effect=[None, CacheLockLostError("Sandbox cleanup lease lost")]
    )
    with pytest.raises(CacheLockLostError, match="Sandbox cleanup lease lost"):
        cleanup.reconcile_sandbox_resources(
            manager, "tenant-a", time.monotonic() + 60, check_ownership
        )
    manager.delete_resource.assert_not_called()
    cache.set.assert_not_called()
