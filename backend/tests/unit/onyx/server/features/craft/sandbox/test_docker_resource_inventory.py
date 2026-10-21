import time
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
    _sandbox_volume_name,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_MANAGED_BY,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.models import SandboxResourceKind


def _legacy_manager() -> tuple[DockerSandboxManager, MagicMock, MagicMock, UUID]:
    sandbox_id = uuid4()
    labels = {
        LABEL_SANDBOX_ID: str(sandbox_id),
        LABEL_TENANT_ID: "tenant-a",
        LABEL_K8S_MANAGED_BY: "onyx",
    }
    container, volume = MagicMock(), MagicMock()
    container.name, container.id, container.labels = "sandbox", "container-1", labels
    stamp = datetime.now(timezone.utc).isoformat()
    container.attrs = {
        "Created": stamp,
        "NetworkSettings": {"Networks": {"craft-network": {}}},
        "Mounts": [{"Type": "volume", "Name": "workspace-volume"}],
    }
    volume.name = "workspace-volume"
    volume.attrs = {"Labels": dict(labels), "CreatedAt": stamp}
    manager = object.__new__(DockerSandboxManager)
    manager._network_name, manager._compose_project = "craft-network", None
    manager._cleanup_docker = MagicMock()
    manager._cleanup_docker.containers.list.return_value = [container]
    manager._cleanup_docker.volumes.list.return_value = [volume]
    return manager, container, volume, sandbox_id


def test_host_legacy_container_and_mounted_volume_are_inventoried() -> None:
    manager, _container, _volume, _sandbox_id = _legacy_manager()
    resources = list(manager.iter_resources("tenant-a", time.monotonic() + 30))
    assert [r.kind for r in resources] == [
        SandboxResourceKind.CONTAINER,
        SandboxResourceKind.VOLUME,
    ]


def test_host_legacy_resources_on_another_network_remain_protected() -> None:
    manager, container, _volume, _sandbox_id = _legacy_manager()
    container.attrs["NetworkSettings"] = {"Networks": {"other-network": {}}}
    assert list(manager.iter_resources("tenant-a", time.monotonic() + 30)) == []


def test_mounted_volume_must_match_full_sandbox_identity() -> None:
    manager, _container, volume, _sandbox_id = _legacy_manager()
    volume.attrs["Labels"][LABEL_SANDBOX_ID] = str(uuid4())
    resources = list(manager.iter_resources("tenant-a", time.monotonic() + 30))
    assert [r.kind for r in resources] == [SandboxResourceKind.CONTAINER]


def test_volume_delete_never_forces_in_use_storage_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _container, volume, _sandbox_id = _legacy_manager()
    resource = list(manager.iter_resources("tenant-a", time.monotonic() + 30))[1]
    monkeypatch.setattr(
        manager._cleanup_docker.volumes, "get", MagicMock(return_value=volume)
    )
    manager.delete_resource(resource, time.monotonic() + 30)
    volume.remove.assert_called_once_with(force=False)


def test_specific_sandbox_can_inventory_a_detached_owned_legacy_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _container, volume, sandbox_id = _legacy_manager()
    volume.name = _sandbox_volume_name(sandbox_id)
    monkeypatch.setattr(
        manager._cleanup_docker.containers, "list", MagicMock(return_value=[])
    )
    resources = list(
        manager.iter_resources("tenant-a", time.monotonic() + 30, sandbox_id)
    )
    assert [r.kind for r in resources] == [SandboxResourceKind.VOLUME]
