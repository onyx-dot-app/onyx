from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call
from uuid import UUID, uuid4

import pytest
from kubernetes.client.rest import ApiException

from onyx.background.celery.tasks.build import tasks
from onyx.cache.interface import CacheLockLostError
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as ksm,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
)
from onyx.server.features.build.session import sandbox_lifecycle as lifecycle


def _runtime(sandbox: Sandbox) -> SandboxResource:
    return SandboxResource(
        kind=SandboxResourceKind.POD,
        name="sandbox",
        instance_id="runtime-1",
        sandbox_id=sandbox.id,
        tenant_id="tenant-a",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "failure", ["history", "snapshot", "discovery", "rescan", "delete"]
)
def test_cleanup_keeps_runtime_and_ports_after_checkpoint_or_delete_failure(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=SandboxStatus.RUNNING,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
        provisioning_attempt_number=1,
    )
    session_id = uuid4()
    manager, db_session, lock = MagicMock(), MagicMock(), MagicMock()
    manager.iter_resources.return_value = [_runtime(sandbox)]
    manager.workspace_storage_identity.return_value = "workspace-v1"
    monkeypatch.setattr(
        lifecycle, "record_cleanup_checkpoint__no_commit", lambda *_args: True
    )
    manager.health_check.return_value = False
    manager.supports_opencode_history_persistence = True
    manager.list_session_workspaces.return_value = [session_id]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    snapshot = MagicMock()
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)
    if failure == "history":
        manager.create_opencode_history_snapshot.side_effect = RuntimeError(
            "history failed"
        )
    elif failure == "snapshot":
        snapshot.side_effect = RuntimeError("snapshot failed")
    elif failure == "discovery":
        manager.list_session_workspaces.side_effect = RuntimeError("discovery failed")
    elif failure == "rescan":
        manager.list_session_workspaces.side_effect = [
            [session_id],
            RuntimeError("rescan failed"),
        ]
    else:
        manager.terminate_observed_resources.side_effect = RuntimeError("delete failed")

    if failure in {"discovery", "rescan", "delete"}:
        with pytest.raises(RuntimeError, match="failed"):
            lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    else:
        lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    if failure != "delete":
        manager.terminate_observed_resources.assert_not_called()
    db_session.execute.assert_not_called()
    assert db_session.commit.call_count == (1 if failure == "delete" else 0)


@pytest.mark.parametrize(
    "output", ["", "00000000-0000-0000-0000-000000000001", "ls: permission denied"]
)
def test_kubernetes_discovery_requires_completion(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._stream_core_api = MagicMock()
    monkeypatch.setattr(ksm, "k8s_stream", lambda *_args, **_kwargs: output)
    with pytest.raises(RuntimeError, match="Incomplete workspace discovery"):
        manager.list_session_workspaces(uuid4())


def test_kubernetes_discovery_propagates_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._stream_core_api = MagicMock()
    monkeypatch.setattr(
        ksm, "k8s_stream", MagicMock(side_effect=ApiException(status=500))
    )
    with pytest.raises(RuntimeError, match="Workspace discovery failed"):
        manager.list_session_workspaces(uuid4())


def test_kubernetes_verified_empty_workspace_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._stream_core_api = MagicMock()
    monkeypatch.setattr(
        ksm, "k8s_stream", lambda *_args, **_kwargs: "\nONYX_WORKSPACE_LIST_COMPLETE\n"
    )
    assert manager.list_session_workspaces(uuid4()) == []


def test_cleanup_deadline_and_lease_loss_stop_work() -> None:
    lease = MagicMock()
    with pytest.raises(TimeoutError):
        tasks._check_cleanup_lease(lease, 0)
    lease.extend.assert_not_called()
    lease.owned.return_value = False
    with pytest.raises(CacheLockLostError):
        tasks._check_cleanup_lease(lease, float("inf"))
    lease.extend.assert_not_called()
    lease.owned.return_value = True
    tasks._check_cleanup_lease(lease, float("inf"))
    lease.extend.assert_called_once_with(tasks.SESSION_FLOW_LOCK_LEASE_SECONDS)


def test_sweep_checks_all_running_pages_before_the_next_scheduled_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandboxes = [Sandbox(id=UUID(int=i), user_id=uuid4()) for i in range(1, 202)]
    cache = MagicMock()
    cursor_values: dict[str, bytes] = {}
    cache.get.side_effect = cursor_values.get
    cache.set.side_effect = lambda key, value: cursor_values.update(
        {key: value.encode()}
    )
    cache.delete.side_effect = lambda key: cursor_values.pop(key, None)
    pages = MagicMock(
        side_effect=[sandboxes[:100], sandboxes[100:200], sandboxes[200:], []]
    )
    stale = MagicMock(return_value=False)
    session = MagicMock()
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(tasks, "get_redis_client", MagicMock())
    monkeypatch.setattr(tasks, "get_sandbox_manager", MagicMock())
    monkeypatch.setattr(tasks, "reconcile_sandbox_resources", MagicMock())
    monkeypatch.setattr(tasks, "maybe_mark_tenant_active", MagicMock())
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", lambda: session)
    monkeypatch.setattr(tasks, "get_running_sandboxes", pages)
    monkeypatch.setattr(tasks, "user_has_stale_active_session", stale)
    monkeypatch.setattr(lifecycle, "is_sandbox_idle", lambda *_args: False)

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]

    assert stale.call_count == 201
    assert pages.call_args_list == [
        call(session.__enter__.return_value, after_id=after_id, limit=100)
        for after_id in (None, sandboxes[99].id, sandboxes[199].id, sandboxes[200].id)
    ]
    assert tasks.RUNNING_SANDBOX_CURSOR_KEY not in cursor_values


def test_expired_sweep_resumes_after_a_slow_failed_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandboxes = [Sandbox(id=UUID(int=i), user_id=uuid4()) for i in (1, 2)]
    elapsed = 0.0
    cache = MagicMock()
    cursor_values: dict[str, bytes] = {}
    cache.get.side_effect = cursor_values.get
    cache.set.side_effect = lambda key, value: cursor_values.update(
        {key: value.encode()}
    )
    cache.delete.side_effect = lambda key: cursor_values.pop(key, None)
    attempted: list[UUID] = []

    def sleep(*_args: object, sandbox: Sandbox, **_kwargs: object) -> None:
        nonlocal elapsed
        attempted.append(sandbox.id)
        if sandbox.id == sandboxes[0].id:
            elapsed += tasks.TIMEOUT_SECONDS + 1
            raise RuntimeError("checkpoint timed out")

    def page(*_args: object, after_id: UUID | None, limit: int) -> list[Sandbox]:
        return [s for s in sandboxes if after_id is None or s.id > after_id][:limit]

    monkeypatch.setattr(tasks.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(tasks, "get_redis_client", MagicMock())
    monkeypatch.setattr(tasks, "get_sandbox_manager", MagicMock())
    monkeypatch.setattr(tasks, "reconcile_sandbox_resources", MagicMock())
    monkeypatch.setattr(tasks, "maybe_mark_tenant_active", MagicMock())
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(tasks, "get_running_sandboxes", page)
    monkeypatch.setattr(lifecycle, "is_sandbox_idle", lambda *_args: True)
    monkeypatch.setattr(lifecycle, "sleep_sandbox", sleep)

    with pytest.raises(TimeoutError):
        tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]
    assert (
        cursor_values[tasks.RUNNING_SANDBOX_CURSOR_KEY] == str(sandboxes[0].id).encode()
    )

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")  # ty: ignore[invalid-argument-type]

    assert attempted == [s.id for s in sandboxes]
    assert tasks.RUNNING_SANDBOX_CURSOR_KEY not in cursor_values


def test_runtime_change_during_checkpoint_aborts_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=SandboxStatus.RUNNING,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
        provisioning_attempt_number=1,
    )
    manager, db_session, lock = MagicMock(), MagicMock(), MagicMock()
    manager.supports_opencode_history_persistence = False
    manager.list_session_workspaces.return_value = []
    manager.iter_resources.side_effect = [
        [_runtime(sandbox)],
        [_runtime(sandbox).model_copy(update={"instance_id": "new-runtime"})],
    ]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    manager.terminate_observed_resources.assert_not_called()
    db_session.commit.assert_not_called()


def test_confirmed_missing_storage_can_complete_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=SandboxStatus.RUNNING,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
        provisioning_attempt_number=1,
    )
    manager, db_session, lock = MagicMock(), MagicMock(), MagicMock()
    manager.workspace_storage_exists.return_value = False
    manager.workspace_storage_identity.return_value = None
    manager.iter_resources.return_value = []
    monkeypatch.setattr(
        lifecycle, "sleep_running_sandbox__no_commit", lambda *_args: True
    )
    monkeypatch.setattr(lifecycle, "clear_nextjs_ports_for_user", lambda *_args: 0)
    monkeypatch.setattr(
        lifecycle, "mark_user_sessions_idle__no_commit", lambda *_args: 0
    )
    lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    manager.create_opencode_history_snapshot.assert_not_called()
    manager.list_session_workspaces.assert_not_called()
    manager.terminate_observed_resources.assert_called_once()
    db_session.commit.assert_called_once()


def test_existing_storage_without_owned_inventory_cannot_sleep() -> None:
    sandbox = Sandbox(id=uuid4(), user_id=uuid4(), provisioning_attempt_number=1)
    manager, session, lock = MagicMock(), MagicMock(), MagicMock()
    manager.workspace_storage_exists.return_value = True
    manager.iter_resources.return_value = []
    with pytest.raises(RuntimeError, match="Cannot verify workspace storage inventory"):
        lifecycle.sleep_sandbox(session, manager, sandbox, "tenant-a", lock)
    manager.terminate_observed_resources.assert_not_called()
    session.commit.assert_not_called()


def test_missing_storage_retries_partial_deletion_without_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=SandboxStatus.RUNNING,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
        provisioning_attempt_number=1,
    )
    manager, db_session, lock = MagicMock(), MagicMock(), MagicMock()
    manager.iter_resources.return_value = [_runtime(sandbox)]
    manager.supports_opencode_history_persistence = True
    manager.workspace_storage_exists.side_effect = [True, False]
    manager.workspace_storage_identity.side_effect = [
        "workspace-v1",
        "workspace-v1",
        None,
    ]
    manager.list_session_workspaces.return_value = []
    manager.terminate_observed_resources.side_effect = [
        RuntimeError("secret deletion failed"),
        None,
    ]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    monkeypatch.setattr(
        lifecycle, "record_cleanup_checkpoint__no_commit", lambda *_args: True
    )
    monkeypatch.setattr(
        lifecycle, "sleep_running_sandbox__no_commit", lambda *_args: True
    )
    monkeypatch.setattr(lifecycle, "clear_nextjs_ports_for_user", lambda *_args: 0)
    monkeypatch.setattr(
        lifecycle, "mark_user_sessions_idle__no_commit", lambda *_args: 0
    )
    with pytest.raises(RuntimeError, match="secret deletion failed"):
        lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    db_session.commit.assert_called_once()

    lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)

    manager.create_opencode_history_snapshot.assert_called_once()
    assert manager.list_session_workspaces.call_count == 2
    assert manager.terminate_observed_resources.call_count == 2
    assert db_session.commit.call_count == 2


@pytest.mark.parametrize("status", [404, 500])
def test_kubernetes_missing_storage_requires_not_found(status: int) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.side_effect = ApiException(status=status)
    if status == 404:
        assert not manager.workspace_storage_exists(uuid4(), "tenant-a")
    else:
        with pytest.raises(ApiException):
            manager.workspace_storage_exists(uuid4(), "tenant-a")
