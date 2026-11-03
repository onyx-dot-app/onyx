"""Resource-only checks never seed or reset the deployed application's database."""

from collections.abc import Generator

import pytest
from kubernetes import client

from onyx.server.features.build.configs import SANDBOX_BACKEND, SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.k8s_client import build_core_v1_api
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from tests.common.craft.kubernetes_resources import CleanupNamespace


@pytest.fixture(scope="session")
def k8s_client() -> client.CoreV1Api:
    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip("Requires the Craft Kubernetes integration deployment")
    return build_core_v1_api()


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed() -> None:
    pass


@pytest.fixture(scope="module", autouse=True)
def _reap_module_pods() -> None:
    pass


@pytest.fixture(scope="module", autouse=True)
def _sandbox_push_key() -> None:
    pass


@pytest.fixture
def cleanup_namespace(k8s_client: client.CoreV1Api) -> Generator[CleanupNamespace]:
    namespace = k8s_client.create_namespace(
        client.V1Namespace(
            metadata=client.V1ObjectMeta(generate_name="craft-cleanup-test-")
        )
    )
    name = namespace.metadata.name
    manager = KubernetesSandboxManager()
    manager._namespace = name
    try:
        yield CleanupNamespace(name, k8s_client, manager)
    finally:
        for service in k8s_client.list_namespaced_service(name).items:
            if service.metadata.finalizers:
                k8s_client.patch_namespaced_service(
                    service.metadata.name, name, {"metadata": {"finalizers": None}}
                )
        k8s_client.delete_namespace(
            name,
            body=client.V1DeleteOptions(
                preconditions=client.V1Preconditions(uid=namespace.metadata.uid)
            ),
        )
