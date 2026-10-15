"""Resource ownership and failed provisioning against the deployed Kubernetes API."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.kubernetes_runtime import KubernetesRuntime
from onyx.server.features.build.sandbox.labels import (
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_PROTOCOL,
)
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.sandbox.models import LegacySandboxError
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _resources(
    runtime: KubernetesRuntime, sandbox_id: UUID
) -> list[tuple[str, Callable[..., Any], Callable[..., Any]]]:
    name = runtime.pod_name(sandbox_id)
    return [
        (
            name,
            runtime.core_api.read_namespaced_pod,
            runtime.core_api.delete_namespaced_pod,
        ),
        (
            name,
            runtime.core_api.read_namespaced_service,
            runtime.core_api.delete_namespaced_service,
        ),
        (
            f"{name}-opencode-auth",
            runtime.core_api.read_namespaced_secret,
            runtime.core_api.delete_namespaced_secret,
        ),
    ]


def _assert_absent(runtime: KubernetesRuntime, sandbox_id: UUID) -> None:
    for name, read, _delete in _resources(runtime, sandbox_id):
        with pytest.raises(ApiException) as exc:
            read(name=name, namespace=runtime.namespace)
        assert exc.value.status == 404, name


def _delete_owned_resources(
    runtime: KubernetesRuntime, sandbox_id: UUID, *, legacy_name: str | None = None
) -> None:
    resources = _resources(runtime, sandbox_id)
    if legacy_name is not None:
        resources.append(
            (
                legacy_name,
                runtime.core_api.read_namespaced_pod,
                runtime.core_api.delete_namespaced_pod,
            )
        )
    for name, read, delete in resources:
        try:
            resource = read(name=name, namespace=runtime.namespace)
        except ApiException as error:
            if error.status == 404:
                continue
            raise
        assert resource.metadata.labels[LABEL_SANDBOX_ID] == str(sandbox_id)
        delete(
            name=name,
            namespace=runtime.namespace,
            body=client.V1DeleteOptions(
                preconditions=client.V1Preconditions(uid=resource.metadata.uid)
            ),
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                read(name=name, namespace=runtime.namespace)
            except ApiException as error:
                if error.status == 404:
                    break
                raise
            time.sleep(0.5)
        else:
            pytest.fail(f"Test resource {name} was not deleted")


def _held_pod(runtime: KubernetesRuntime, sandbox_id: UUID) -> client.V1Pod:
    pod = runtime._create_sandbox_pod(
        sandbox_id=str(sandbox_id),
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        provisioning_attempt_number=1,
    )
    # Exercise control-plane ownership without booting a VM for identity checks.
    pod.spec.scheduling_gates = [
        client.V1PodSchedulingGate(name="onyx.app/runtime-resource-test")
    ]
    return pod


@pytest.mark.parametrize("failure", ["initialize", "admission-label"])
def test_failed_provision_removes_only_attempt_created_resources(
    k8s_manager: SandboxManager, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Fault injection delegates creation to the real API, never a fake client."""
    runtime = k8s_manager._runtime
    assert isinstance(runtime, KubernetesRuntime)
    sandbox_id = uuid4()
    _assert_absent(runtime, sandbox_id)
    created_pod_uids: list[str] = []
    initialize_called = False
    create_pod = runtime.core_api.create_namespaced_pod
    existing_service_uid: str | None = None

    def create_with_fault(
        namespace: str, body: client.V1Pod, **kwargs: Any
    ) -> client.V1Pod:
        if failure == "admission-label":
            body.metadata.labels[LABEL_SANDBOX_PROTOCOL] = "invalid-test-protocol"
        created = create_pod(namespace=namespace, body=body, **kwargs)
        assert created.metadata.uid
        created_pod_uids.append(created.metadata.uid)
        return created

    monkeypatch.setattr(runtime.core_api, "create_namespaced_pod", create_with_fault)

    def fail_initialize(actual_id: UUID, remaining_seconds: float) -> None:
        nonlocal initialize_called
        initialize_called = True
        assert actual_id == sandbox_id
        assert remaining_seconds > 0
        for name, read, _delete in _resources(runtime, sandbox_id):
            resource = read(name=name, namespace=runtime.namespace)
            assert resource.metadata.uid
            assert resource.metadata.labels[LABEL_SANDBOX_ID] == str(sandbox_id)
        raise RuntimeError("injected initialize failure")

    try:
        if failure == "admission-label":
            existing_service = runtime.core_api.create_namespaced_service(
                runtime.namespace,
                runtime._create_sandbox_service(
                    sandbox_id, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
                ),
            )
            existing_service_uid = existing_service.metadata.uid
            assert existing_service_uid
        expected_error = RuntimeError if failure == "initialize" else LegacySandboxError
        expected_message = (
            "injected initialize failure"
            if failure == "initialize"
            else "not a Firecracker sandbox resource"
        )
        with pytest.raises(expected_error, match=expected_message):
            runtime.provision(
                sandbox_id=sandbox_id,
                user_id=uuid4(),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                onyx_pat="runtime-resource-test-no-provider-request",
                provisioning_attempt_number=1,
                initialize=fail_initialize,
            )
        assert len(created_pod_uids) == 1
        assert initialize_called is (failure == "initialize")
        if existing_service_uid is None:
            _assert_absent(runtime, sandbox_id)
        else:
            preserved = runtime.core_api.read_namespaced_service(
                runtime.pod_name(sandbox_id), runtime.namespace
            )
            assert preserved.metadata.uid == existing_service_uid
            assert preserved.metadata.deletion_timestamp is None
            pod_resource, _service_resource, secret_resource = _resources(
                runtime, sandbox_id
            )
            for name, read, _delete in (pod_resource, secret_resource):
                with pytest.raises(ApiException) as exc:
                    read(name=name, namespace=runtime.namespace)
                assert exc.value.status == 404, name
    finally:
        _delete_owned_resources(runtime, sandbox_id)


def test_legacy_short_name_pod_is_rejected_and_preserved(
    k8s_manager: SandboxManager,
) -> None:
    runtime = k8s_manager._runtime
    assert isinstance(runtime, KubernetesRuntime)
    sandbox_id = uuid4()
    legacy_name = f"sandbox-{str(sandbox_id)[:8]}"
    _assert_absent(runtime, sandbox_id)
    pod = _held_pod(runtime, sandbox_id)
    pod.metadata.name = legacy_name
    pod.metadata.labels.pop(LABEL_SANDBOX_PROTOCOL)
    created = runtime.core_api.create_namespaced_pod(runtime.namespace, pod)
    try:
        with pytest.raises(LegacySandboxError, match="snapshotted and drained"):
            runtime.get_pod(sandbox_id)
        with pytest.raises(LegacySandboxError):
            runtime.terminate(sandbox_id)
        preserved = runtime.core_api.read_namespaced_pod(legacy_name, runtime.namespace)
        assert preserved.metadata.uid == created.metadata.uid
        assert preserved.metadata.deletion_timestamp is None
        _assert_absent(runtime, sandbox_id)
    finally:
        _delete_owned_resources(runtime, sandbox_id, legacy_name=legacy_name)


def test_same_prefix_sandboxes_have_distinct_actual_pods(
    k8s_manager: SandboxManager,
) -> None:
    runtime = k8s_manager._runtime
    assert isinstance(runtime, KubernetesRuntime)
    first = uuid4()
    second = UUID(hex=first.hex[:8] + uuid4().hex[8:])
    assert str(first)[:8] == str(second)[:8]
    assert first != second
    try:
        for sandbox_id in (first, second):
            _assert_absent(runtime, sandbox_id)
            runtime.core_api.create_namespaced_pod(
                runtime.namespace, _held_pod(runtime, sandbox_id)
            )
        first_pod = runtime.get_pod(first)
        second_pod = runtime.get_pod(second)
        assert first_pod is not None and second_pod is not None
        assert first_pod.metadata.name == f"sandbox-{first.hex}"
        assert second_pod.metadata.name == f"sandbox-{second.hex}"
        assert first_pod.metadata.uid != second_pod.metadata.uid
        assert first_pod.metadata.labels[LABEL_SANDBOX_ID] == str(first)
        assert second_pod.metadata.labels[LABEL_SANDBOX_ID] == str(second)
    finally:
        for sandbox_id in (first, second):
            _delete_owned_resources(runtime, sandbox_id)
