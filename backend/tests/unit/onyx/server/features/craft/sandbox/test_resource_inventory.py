import time
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.docker import docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as ksm,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_AUTH,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
)


def test_docker_cleanup_timeout_does_not_shorten_bulk_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock()
    monkeypatch.setattr(dsm, "DockerClient", factory)
    monkeypatch.setattr(dsm, "SANDBOX_PROXY_HOST", "proxy")
    monkeypatch.setattr(dsm, "get_default_file_store", MagicMock())
    monkeypatch.setattr(dsm, "_detect_compose_project", lambda _client: None)
    manager = dsm.DockerSandboxManager()
    assert "timeout" not in factory.call_args_list[0].kwargs
    assert factory.call_args_list[1].kwargs["timeout"] == 15
    assert manager._cleanup_docker is factory.return_value


@pytest.mark.parametrize("expires_during_request", [False, True])
def test_docker_inventory_stops_requests_when_deadline_expires(
    expires_during_request: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(dsm.DockerSandboxManager)
    manager._cleanup_docker = MagicMock()
    clock = MagicMock(return_value=0.0 if expires_during_request else 2.0)
    monkeypatch.setattr(dsm.time, "monotonic", clock)

    def list_containers(**_kwargs: object) -> list[object]:
        clock.return_value = 2.0
        return []

    manager._cleanup_docker.containers.list.side_effect = list_containers
    with pytest.raises(TimeoutError):
        list(manager.iter_resources("tenant-a", deadline=1.0))
    assert manager._cleanup_docker.containers.list.call_count == int(
        expires_during_request
    )
    manager._cleanup_docker.volumes.list.assert_not_called()


@pytest.mark.parametrize(
    "kind", [SandboxResourceKind.CONTAINER, SandboxResourceKind.VOLUME]
)
def test_docker_inventory_rejects_foreign_network_with_matching_compose_project(
    kind: SandboxResourceKind,
) -> None:
    manager = object.__new__(dsm.DockerSandboxManager)
    manager._cleanup_docker = MagicMock()
    manager._network_name = "deployment-network"
    manager._compose_project = "onyx"
    items = []
    for name, network in (
        ("owned", "deployment-network"),
        ("foreign", "other-network"),
        ("legacy", None),
    ):
        item = MagicMock()
        item.name = name
        item.id = name
        item.labels = dsm.build_sandbox_labels(
            uuid4(), "tenant-a", None, compose_project="onyx"
        )
        if network is None:
            item.labels.pop(dsm.LABEL_DOCKER_NETWORK)
        else:
            item.labels[dsm.LABEL_DOCKER_NETWORK] = network
        item.attrs = {
            "Labels": item.labels,
            "Created": "2026-10-21T10:00:00Z",
            "CreatedAt": "2026-10-21T10:00:00Z",
        }
        items.append(item)
    manager._cleanup_docker.containers.list.return_value = (
        items if kind == SandboxResourceKind.CONTAINER else []
    )
    manager._cleanup_docker.volumes.list.return_value = (
        items if kind == SandboxResourceKind.VOLUME else []
    )

    resources = list(manager.iter_resources("tenant-a", time.monotonic() + 30))

    assert [(resource.kind, resource.name) for resource in resources] == [
        (kind, "owned"),
        (kind, "legacy"),
    ]


def test_pod_log_stream_preserves_lines_without_an_idle_read_timeout() -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    stream = manager._core_api.read_namespaced_pod_log.return_value
    stream.stream.return_value = iter([b"first\n", b"second\n"])

    assert list(manager.stream_pod_logs(uuid4())) == ["first", "second"]
    timeout = manager._core_api.read_namespaced_pod_log.call_args.kwargs[
        "_request_timeout"
    ]
    assert timeout == (ksm.CONNECT_TIMEOUT_SECONDS, None)
    stream.close.assert_called_once()


def _resource() -> SandboxResource:
    return SandboxResource(
        kind=SandboxResourceKind.POD,
        name="sandbox-12345678",
        instance_id="old-uid",
        sandbox_id=uuid4(),
        tenant_id="tenant-a",
        created_at=datetime.now(timezone.utc),
    )


def _metadata(resource: SandboxResource) -> client.V1ObjectMeta:
    return client.V1ObjectMeta(
        name=resource.name,
        uid=resource.instance_id,
        resource_version="12",
        creation_timestamp=resource.created_at,
        labels={
            LABEL_SANDBOX_ID: str(resource.sandbox_id),
            LABEL_TENANT_ID: resource.tenant_id,
            LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
            LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
        },
    )


@pytest.mark.parametrize(
    "change", ["uid", "tenant", "sandbox", "component", "missing_component"]
)
def test_delete_rejects_replaced_or_foreign_resource(change: str) -> None:
    resource = _resource()
    metadata = _metadata(resource)
    if change == "uid":
        metadata.uid = "new-uid"
    elif change == "tenant":
        metadata.labels[LABEL_TENANT_ID] = "tenant-b"
    elif change == "sandbox":
        metadata.labels[LABEL_SANDBOX_ID] = str(uuid4())
    elif change == "component":
        metadata.labels[LABEL_K8S_COMPONENT] = "other"
    else:
        metadata.labels.pop(LABEL_K8S_COMPONENT)
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.return_value = client.V1Pod(metadata=metadata)
    with pytest.raises(RuntimeError, match="ownership changed"):
        manager.delete_resource(resource, time.monotonic() + 10)
    manager._core_api.delete_namespaced_pod.assert_not_called()


@pytest.mark.parametrize(
    "component", [LABEL_K8S_COMPONENT_SANDBOX, LABEL_K8S_COMPONENT_AUTH]
)
def test_delete_uses_uid_and_resource_version_preconditions(component: str) -> None:
    resource = _resource()
    metadata = _metadata(resource)
    metadata.labels[LABEL_K8S_COMPONENT] = component
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.side_effect = [
        client.V1Pod(metadata=metadata),
        ApiException(status=404),
    ]
    manager.delete_resource(resource, time.monotonic() + 10)
    options = manager._core_api.delete_namespaced_pod.call_args.kwargs["body"]
    assert options.preconditions.uid == "old-uid"
    assert options.preconditions.resource_version == "12"


def test_inventory_paginates_and_excludes_other_tenants() -> None:
    resource, foreign = _resource(), _resource()
    foreign = foreign.model_copy(update={"tenant_id": "tenant-b"})
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.list_namespaced_pod.side_effect = [
        client.V1PodList(
            items=[client.V1Pod(metadata=_metadata(resource))],
            metadata=client.V1ListMeta(_continue="next"),
        ),
        client.V1PodList(
            items=[client.V1Pod(metadata=_metadata(foreign))],
            metadata=client.V1ListMeta(),
        ),
    ]
    manager._core_api.list_namespaced_service.return_value = client.V1ServiceList(
        items=[], metadata=client.V1ListMeta()
    )
    manager._core_api.list_namespaced_secret.return_value = client.V1SecretList(
        items=[], metadata=client.V1ListMeta()
    )
    assert list(manager.iter_resources("tenant-a", time.monotonic() + 10)) == [resource]
    calls = manager._core_api.list_namespaced_pod.call_args_list
    assert calls[1].kwargs["_continue"] == "next"
    assert calls[0].kwargs["limit"] == 100
    assert "onyx.app/tenant-id=tenant-a" in calls[0].kwargs["label_selector"]
    assert calls[0].kwargs["_request_timeout"] <= 10


def test_readiness_watch_uses_remaining_operation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.return_value = client.V1Pod(
        metadata=client.V1ObjectMeta(resource_version="12")
    )
    monkeypatch.setattr(
        manager, "_evaluate_pod_readiness", MagicMock(side_effect=[False, True])
    )
    watcher = MagicMock()
    watcher.stream.return_value = iter(
        [
            {
                "type": "MODIFIED",
                "object": client.V1Pod(
                    metadata=client.V1ObjectMeta(resource_version="13")
                ),
            }
        ]
    )
    monkeypatch.setattr(ksm.watch, "Watch", lambda: watcher)
    assert manager._wait_for_pod_ready("sandbox-test", time.monotonic() + 60)
    assert 0 < watcher.stream.call_args.kwargs["_request_timeout"] <= 60
