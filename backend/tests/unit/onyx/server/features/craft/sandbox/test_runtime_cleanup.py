import logging
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from docker.errors import APIError, NotFound
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as ksm,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


def test_service_delete_failure_does_not_skip_pod_or_secret() -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.delete_namespaced_service.side_effect = ApiException(status=500)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        manager._cleanup_kubernetes_resources(str(uuid4()), wait_for_deletion=False)
    manager._core_api.delete_namespaced_pod.assert_called_once()
    manager._core_api.delete_namespaced_secret.assert_called_once()


def test_deletion_wait_failure_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    monkeypatch.setattr(manager, "_wait_for_resource_deletion", lambda *_args: False)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        manager._cleanup_kubernetes_resources(str(uuid4()))


def test_secret_delete_failure_is_not_success() -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.delete_namespaced_secret.side_effect = ApiException(status=403)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        manager._cleanup_kubernetes_resources(str(uuid4()), wait_for_deletion=False)


@pytest.mark.parametrize("resource_remains", [False, True])
def test_exhausted_budget_checks_remaining_resources_once(
    resource_remains: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    monkeypatch.setattr(ksm, "RUNTIME_TEARDOWN_SECONDS", 0)
    for read in (
        manager._core_api.read_namespaced_service,
        manager._core_api.read_namespaced_pod,
        manager._core_api.read_namespaced_secret,
    ):
        read.side_effect = ApiException(status=404)
    if resource_remains:
        manager._core_api.read_namespaced_secret.side_effect = None
        with pytest.raises(RuntimeError, match="secret .* remains"):
            manager._cleanup_kubernetes_resources(str(uuid4()))
    else:
        manager._cleanup_kubernetes_resources(str(uuid4()))
    manager._core_api.read_namespaced_service.assert_called_once()
    manager._core_api.read_namespaced_pod.assert_called_once()
    manager._core_api.read_namespaced_secret.assert_called_once()


@pytest.mark.parametrize("failure", ["container", "volume"])
def test_docker_cleanup_reports_removal_failure(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = object.__new__(DockerSandboxManager)
    manager._docker = MagicMock()
    container = MagicMock()
    monkeypatch.setattr(manager, "_get_container", lambda _sandbox_id: container)
    monkeypatch.setattr(manager, "_close_all_sandbox_buses", lambda _sandbox_id: None)
    volume = manager._docker.volumes.get.return_value
    if failure == "container":
        container.remove.side_effect = APIError("remove failed")
    else:
        volume.remove.side_effect = APIError("remove failed")
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        manager.terminate(uuid4())
    volume.remove.assert_called_once()


def test_docker_cleanup_accepts_already_missing_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(DockerSandboxManager)
    manager._docker = MagicMock()
    manager._docker.volumes.get.side_effect = NotFound("missing")
    monkeypatch.setattr(manager, "_get_container", lambda _sandbox_id: None)
    monkeypatch.setattr(manager, "_close_all_sandbox_buses", lambda _sandbox_id: None)
    manager.terminate(uuid4())


def test_docker_cleanup_logs_container_disappearing_during_removal(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = object.__new__(DockerSandboxManager)
    manager._docker = MagicMock()
    container = MagicMock()
    container.name = "sandbox-test"
    container.remove.side_effect = NotFound("missing")
    monkeypatch.setattr(manager, "_get_container", lambda _sandbox_id: container)
    monkeypatch.setattr(manager, "_close_all_sandbox_buses", lambda _sandbox_id: None)

    with caplog.at_level(logging.WARNING):
        manager.terminate(uuid4())

    assert "Sandbox container sandbox-test disappeared during removal." in caplog.text
