"""Real Kubernetes resources owned by one cleanup test namespace."""

import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)

ResourceKind = Literal["pod", "service", "secret"]
TEST_FINALIZER = "cleanup.tests.onyx.app/hold"


@dataclass(frozen=True)
class CleanupNamespace:
    name: str
    core: client.CoreV1Api
    manager: KubernetesSandboxManager

    def create(self, sandbox_id: UUID, tenant: str = "public", attempt: int = 1) -> str:
        name = f"sandbox-{str(sandbox_id)[:8]}"
        labels = {
            LABEL_SANDBOX_ID: str(sandbox_id),
            LABEL_TENANT_ID: tenant,
            LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
            LABEL_K8S_COMPONENT: "sandbox",
            "onyx.app/provisioning-attempt": str(attempt),
        }
        self.core.create_namespaced_pod(
            self.name,
            client.V1Pod(
                metadata=client.V1ObjectMeta(name=name, labels=labels),
                spec=client.V1PodSpec(
                    automount_service_account_token=False,
                    termination_grace_period_seconds=0,
                    containers=[
                        client.V1Container(
                            name="sandbox",
                            image=SANDBOX_CONTAINER_IMAGE,
                            command=["sleep", "3600"],
                            resources=client.V1ResourceRequirements(
                                requests={"cpu": "1m", "memory": "16Mi"},
                                limits={"cpu": "100m", "memory": "64Mi"},
                            ),
                        )
                    ],
                ),
            ),
        )
        self.core.create_namespaced_service(
            self.name,
            client.V1Service(
                metadata=client.V1ObjectMeta(name=name, labels=labels),
                spec=client.V1ServiceSpec(
                    selector={LABEL_SANDBOX_ID: str(sandbox_id)},
                    ports=[client.V1ServicePort(port=4096)],
                ),
            ),
        )
        self.core.create_namespaced_secret(
            self.name,
            client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=f"{name}-opencode-auth",
                    labels={**labels, LABEL_K8S_COMPONENT: "sandbox-opencode-auth"},
                ),
                string_data={"password": "cleanup-test-only"},
            ),
        )
        return name

    def absent(self, kind: ResourceKind, name: str) -> bool:
        read = {
            "pod": self.core.read_namespaced_pod,
            "service": self.core.read_namespaced_service,
            "secret": self.core.read_namespaced_secret,
        }[kind]
        try:
            read(name, self.name, _request_timeout=10)
        except ApiException as error:
            if error.status == 404:
                return True
            raise
        return False

    def wait_absent(self, kind: ResourceKind, name: str) -> None:
        deadline = time.monotonic() + 30
        while not self.absent(kind, name):
            assert time.monotonic() < deadline, f"{kind} {name} remains"
            time.sleep(0.2)
