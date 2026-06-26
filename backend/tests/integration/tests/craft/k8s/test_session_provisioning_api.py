"""Session provisioning API tests in the Craft k8s integration lane."""

from __future__ import annotations

from contextlib import suppress
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import cleanup_api_user_sandbox_rows
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def test_create_session_provisions_running_sandbox_pod_via_api(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    api_user = UserManager.create(name=f"craft-k8s-session-smoke-{uuid4().hex[:8]}")
    sandbox_id: UUID | None = None
    pod_name: str | None = None
    try:
        session = BuildSessionManager.create(api_user, headless=True)
        sandbox = session.sandbox
        assert sandbox is not None
        assert sandbox.status == SandboxStatus.RUNNING

        sandbox_id = UUID(sandbox.id)
        pod_name = k8s_manager._get_pod_name(sandbox_id)
        pod = k8s_client.read_namespaced_pod(
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
        )
        assert pod.status is not None
        assert pod.status.phase == "Running"
    finally:
        if sandbox_id is not None:
            with suppress(Exception):
                k8s_manager.terminate(sandbox_id)
            # Wait for pod deletion before removing DB rows: the egress proxy resolves
            # sandbox identity via Sandbox.user_id, so deleting the row while the pod
            # is still alive would leave an unattributable orphaned pod.
            if pod_name is not None:
                with suppress(Exception):
                    wait_for_pod_deletion(k8s_client, pod_name)
        cleanup_api_user_sandbox_rows(UUID(api_user.id))
