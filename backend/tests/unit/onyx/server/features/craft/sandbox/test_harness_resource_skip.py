"""Craft cleanup must never list or delete harness sandboxes.

Harness pods and containers carry the same component labels as Craft ones (so
the egress proxy identifies them), plus ``onyx.app/sandbox-kind=harness``.
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.server.features.build.sandbox.docker import docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_KIND,
    LABEL_TENANT_ID,
    NOT_HARNESS_SELECTOR,
    SANDBOX_KIND_HARNESS,
)
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
)

_TENANT = "tenant-a"
_CREATED = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _k8s_manager() -> tuple[KubernetesSandboxManager, MagicMock]:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    core_api = MagicMock()
    manager._core_api = core_api
    return manager, core_api


def _pod(name: str, tenant_id: str, harness: bool) -> client.V1Pod:
    labels = {
        LABEL_SANDBOX_ID: str(uuid4()),
        LABEL_TENANT_ID: tenant_id,
        LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
        LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
    }
    if harness:
        labels[LABEL_SANDBOX_KIND] = SANDBOX_KIND_HARNESS
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            uid=f"{name}-uid",
            resource_version="7",
            creation_timestamp=_CREATED,
            labels=labels,
        )
    )


def _empty_k8s_lists(core_api: MagicMock) -> None:
    core_api.list_namespaced_service.return_value = client.V1ServiceList(
        items=[], metadata=client.V1ListMeta()
    )
    core_api.list_namespaced_secret.return_value = client.V1SecretList(
        items=[], metadata=client.V1ListMeta()
    )


def test_k8s_inventory_skips_harness_pods() -> None:
    manager, core_api = _k8s_manager()
    core_api.list_namespaced_pod.return_value = client.V1PodList(
        items=[
            _pod("sandbox-craft", _TENANT, harness=False),
            _pod("harness-pod", _TENANT, harness=True),
        ],
        metadata=client.V1ListMeta(),
    )
    _empty_k8s_lists(core_api)

    resources = list(manager.iter_resources(_TENANT, time.monotonic() + 10))

    assert [resource.name for resource in resources] == ["sandbox-craft"]
    for list_call in (
        *core_api.list_namespaced_pod.call_args_list,
        *core_api.list_namespaced_secret.call_args_list,
    ):
        assert NOT_HARNESS_SELECTOR in list_call.kwargs["label_selector"]


def test_k8s_tenant_listing_skips_harness_pods() -> None:
    manager, core_api = _k8s_manager()
    core_api.list_namespaced_pod.return_value = client.V1PodList(
        items=[
            _pod("sandbox-craft", "tenant-craft", harness=False),
            _pod("harness-pod", "tenant-harness-only", harness=True),
        ],
        metadata=client.V1ListMeta(),
    )
    _empty_k8s_lists(core_api)

    assert manager.list_resource_tenant_ids(time.monotonic() + 10) == {"tenant-craft"}
    selector = core_api.list_namespaced_pod.call_args.kwargs["label_selector"]
    assert NOT_HARNESS_SELECTOR in selector


def test_k8s_delete_refuses_harness_pod() -> None:
    pod = _pod("harness-pod", _TENANT, harness=True)
    resource = SandboxResource(
        kind=SandboxResourceKind.POD,
        name="harness-pod",
        instance_id="harness-pod-uid",
        sandbox_id=pod.metadata.labels[LABEL_SANDBOX_ID],
        tenant_id=_TENANT,
        created_at=_CREATED,
    )
    manager, core_api = _k8s_manager()
    core_api.read_namespaced_pod.return_value = pod

    with pytest.raises(RuntimeError, match="ownership changed"):
        manager.delete_resource(resource, time.monotonic() + 10)
    core_api.delete_namespaced_pod.assert_not_called()


def _docker_manager() -> tuple[dsm.DockerSandboxManager, MagicMock]:
    manager = object.__new__(dsm.DockerSandboxManager)
    cleanup_docker = MagicMock()
    manager._cleanup_docker = cleanup_docker
    manager._network_name = "deployment-network"
    manager._compose_project = "onyx"
    return manager, cleanup_docker


def _container(name: str, tenant_id: str, harness: bool) -> MagicMock:
    item = MagicMock()
    item.name = name
    item.id = f"{name}-id"
    item.labels = dsm.build_sandbox_labels(
        uuid4(), tenant_id, None, compose_project="onyx"
    )
    item.labels[dsm.LABEL_DOCKER_NETWORK] = "deployment-network"
    if harness:
        item.labels[LABEL_SANDBOX_KIND] = SANDBOX_KIND_HARNESS
    item.attrs = {"Labels": item.labels, "Created": "2026-11-01T10:00:00Z"}
    return item


def test_docker_inventory_skips_harness_containers() -> None:
    manager, cleanup_docker = _docker_manager()
    cleanup_docker.containers.list.return_value = [
        _container("sandbox-craft", _TENANT, harness=False),
        _container("harness-container", _TENANT, harness=True),
    ]
    cleanup_docker.volumes.list.return_value = []

    resources = list(manager.iter_resources(_TENANT, time.monotonic() + 10))

    assert [resource.name for resource in resources] == ["sandbox-craft"]


def test_docker_tenant_listing_skips_harness_containers() -> None:
    manager, cleanup_docker = _docker_manager()
    cleanup_docker.containers.list.return_value = [
        _container("sandbox-craft", "tenant-craft", harness=False),
        _container("harness-container", "tenant-harness-only", harness=True),
    ]
    cleanup_docker.volumes.list.return_value = []

    assert manager.list_resource_tenant_ids(time.monotonic() + 10) == {"tenant-craft"}


def test_docker_delete_refuses_harness_container() -> None:
    container = _container("harness-container", _TENANT, harness=True)
    resource = SandboxResource(
        kind=SandboxResourceKind.CONTAINER,
        name=container.name,
        instance_id=container.id,
        sandbox_id=container.labels[LABEL_SANDBOX_ID],
        tenant_id=_TENANT,
        created_at=_CREATED,
    )
    manager, cleanup_docker = _docker_manager()
    cleanup_docker.containers.get.return_value = container

    with pytest.raises(RuntimeError, match="ownership changed"):
        manager.delete_resource(resource, time.monotonic() + 10)
    container.remove.assert_not_called()
