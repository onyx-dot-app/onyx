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
        manager.terminate.side_effect = RuntimeError("delete failed")

    if failure in {"discovery", "rescan", "delete"}:
        with pytest.raises(RuntimeError, match="failed"):
            lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    else:
        lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", lock)
    if failure != "delete":
        manager.terminate.assert_not_called()
    db_session.execute.assert_not_called()
    db_session.commit.assert_not_called()


@pytest.mark.parametrize("output", ["", str(uuid4()), "ls: permission denied"])
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
