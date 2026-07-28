from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from kubernetes.client.rest import ApiException

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as docker_module
import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as kubernetes_module
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import ExecError
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


def test_kubernetes_workspace_cleanup_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._stream_core_api = MagicMock()  # type: ignore[attr-defined]
    manager._namespace = "sandbox-test"  # type: ignore[attr-defined]
    monkeypatch.setattr(manager, "_close_session_buses", MagicMock())
    monkeypatch.setattr(
        kubernetes_module,
        "k8s_stream",
        MagicMock(side_effect=ApiException(status=500, reason="exec failed")),
    )

    session_id = uuid4()
    with pytest.raises(RuntimeError, match=str(session_id)):
        manager.cleanup_session_workspace(uuid4(), session_id)


def test_docker_workspace_cleanup_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(DockerSandboxManager)
    monkeypatch.setattr(manager, "_close_session_buses", MagicMock())
    monkeypatch.setattr(manager, "_get_container", MagicMock(return_value=object()))
    monkeypatch.setattr(
        docker_module,
        "_run_in_container_as_sandbox_user",
        MagicMock(side_effect=ExecError("exec failed")),
    )

    session_id = uuid4()
    with pytest.raises(RuntimeError, match=str(session_id)):
        manager.cleanup_session_workspace(uuid4(), session_id)
