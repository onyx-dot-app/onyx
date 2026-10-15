"""Session provisioning API tests in the Craft k8s integration lane."""

from __future__ import annotations

from uuid import UUID, uuid4

from kubernetes import client

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import (
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from onyx.server.features.build.session.models import DetailedSessionResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    cleanup_api_user_sandbox,
    kubernetes_runtime,
    register_suite_sandbox,
)


def test_create_session_provisions_running_sandbox_pod_via_api(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    api_user = UserManager.create(name=f"craft-k8s-session-smoke-{uuid4().hex[:8]}")
    sandbox_id: UUID | None = None
    try:
        response = http_client.post(
            f"{API_SERVER_URL}/build/sessions",
            json={"headless": True},
            headers=api_user.headers,
            cookies=api_user.cookies,
        )
        assert response.status_code == 200, (
            f"POST /build/sessions failed: {response.status_code} "
            f"{response.reason_phrase}; body={response.text[:2000]!r}; "
            f"user_id={api_user.id}"
        )
        session = DetailedSessionResponse.model_validate(response.json())
        sandbox = session.sandbox
        assert sandbox is not None
        sandbox_id = UUID(sandbox.id)
        register_suite_sandbox(sandbox_id)
        assert sandbox.status == SandboxStatus.RUNNING
        pod_name = kubernetes_runtime(k8s_manager).pod_name(sandbox_id)
        pod = k8s_client.read_namespaced_pod(
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
        )
        assert pod.status is not None
        assert pod.status.phase == "Running"
        assert pod.spec is not None
        assert pod.spec.runtime_class_name == "kata-fc"
    finally:
        cleanup_api_user_sandbox(k8s_manager, k8s_client, UUID(api_user.id), sandbox_id)
