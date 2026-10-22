from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from kubernetes.client.rest import ApiException

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as ksm,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.session import sandbox_lifecycle as lifecycle


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
    manager.workspace_storage_identity.return_value = "workspace-v1"
    manager.health_check.return_value = False
    manager.supports_opencode_history_persistence = True
    manager.list_session_workspaces.return_value = [session_id]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    snapshot = MagicMock()
    monkeypatch.setattr(lifecycle, "create_session_snapshot_keep_latest", snapshot)
    monkeypatch.setattr(
        lifecycle, "record_cleanup_checkpoint__no_commit", lambda *_args: True
    )
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
        manager.terminate.side_effect = RuntimeError("delete failed")

    if failure in {"discovery", "rescan", "delete"}:
        with pytest.raises(RuntimeError, match="failed"):
            lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    else:
        lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    if failure != "delete":
        manager.terminate.assert_not_called()
    db_session.execute.assert_not_called()
    assert db_session.commit.call_count == int(failure == "delete")


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
    manager.supports_opencode_history_persistence = True
    manager.workspace_storage_exists.side_effect = [True, False]
    manager.workspace_storage_identity.side_effect = [
        "workspace-v1",
        "workspace-v1",
        None,
    ]
    manager.list_session_workspaces.return_value = []
    manager.terminate.side_effect = [RuntimeError("secret deletion failed"), None]
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
    assert manager.terminate.call_count == 2
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
