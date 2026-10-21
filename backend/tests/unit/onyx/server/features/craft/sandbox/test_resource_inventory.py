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
        },
    )


@pytest.mark.parametrize("change", ["uid", "tenant", "sandbox"])
def test_delete_rejects_replaced_or_foreign_resource(change: str) -> None:
    resource = _resource()
    metadata = _metadata(resource)
    if change == "uid":
        metadata.uid = "new-uid"
    elif change == "tenant":
        metadata.labels[LABEL_TENANT_ID] = "tenant-b"
    else:
        metadata.labels[LABEL_SANDBOX_ID] = str(uuid4())
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.return_value = client.V1Pod(metadata=metadata)
    with pytest.raises(RuntimeError, match="ownership changed"):
        manager.delete_resource(resource, time.monotonic() + 10)
    manager._core_api.delete_namespaced_pod.assert_not_called()


def test_delete_uses_uid_and_resource_version_preconditions() -> None:
    resource = _resource()
    manager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"
    manager._core_api = MagicMock()
    manager._core_api.read_namespaced_pod.side_effect = [
        client.V1Pod(metadata=_metadata(resource)),
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
