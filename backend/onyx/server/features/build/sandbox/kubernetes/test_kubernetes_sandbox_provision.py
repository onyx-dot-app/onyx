"""Integration test for KubernetesSandboxManager.provision().

This test requires:
- A running Kubernetes cluster (kind, minikube, or real cluster)
- The SANDBOX_BACKEND=kubernetes environment variable
- The sandbox namespace to exist (default: onyx-sandboxes)
- Service accounts for sandbox (sandbox-runner, sandbox-file-sync)

Run with:
    SANDBOX_BACKEND=kubernetes python -m dotenv -f .vscode/.env run -- \
        pytest backend/tests/integration/tests/build/test_kubernetes_sandbox_provision.py -v
"""

import time
from uuid import UUID

import pytest
from kubernetes import client
from kubernetes import config
from kubernetes.client.rest import ApiException

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.sandbox.kubernetes.manager import (
    KubernetesSandboxManager,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


def _is_kubernetes_available() -> bool:
    """Check if Kubernetes is available and configured."""
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        return True
    except Exception:
        return False


def _get_kubernetes_client() -> client.CoreV1Api:
    """Get a configured Kubernetes CoreV1Api client."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
@pytest.mark.skipif(
    not _is_kubernetes_available(),
    reason="Kubernetes cluster not available",
)
def test_kubernetes_sandbox_provision_happy_path(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Test that provision() creates a sandbox pod and DB record successfully.

    This is a happy path test that:
    1. Creates a BuildSession in the database
    2. Calls provision() to create a Kubernetes pod
    3. Verifies the sandbox is created with RUNNING status
    4. Cleans up by terminating the sandbox
    """
    # Set up tenant context (required for multi-tenant operations)
    tenant_id = "public"
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id: str | None = None
    session_id: str | None = None

    try:
        with get_session_with_current_tenant() as db_session:
            # Create a BuildSession (required since Sandbox has FK to BuildSession)
            user_id = UUID(admin_user.id)
            build_session = create_build_session__no_commit(
                user_id=user_id,
                db_session=db_session,
                name="Test Kubernetes Sandbox Session",
            )
            db_session.commit()
            session_id = str(build_session.id)

            # Call provision
            sandbox_info = manager.provision(
                session_id=session_id,
                tenant_id=tenant_id,
                file_system_path="/tmp/test-files",  # Not used by K8s manager
                db_session=db_session,
                snapshot_id=None,
            )

            # Store sandbox_id for cleanup
            sandbox_id = sandbox_info.id

            # Verify the return value
            assert sandbox_info.id is not None
            assert sandbox_info.session_id == session_id
            assert sandbox_info.status == SandboxStatus.RUNNING
            assert sandbox_info.directory_path.startswith("k8s://")

            # Verify the sandbox exists in the database
            db_sandbox = get_sandbox_by_session_id(db_session, build_session.id)
            assert db_sandbox is not None
            assert db_sandbox.status == SandboxStatus.RUNNING

            # Verify Kubernetes resources exist
            k8s_client = _get_kubernetes_client()
            pod_name = f"sandbox-{session_id[:8]}"
            service_name = pod_name
            configmap_name = f"sandbox-instructions-{session_id[:8]}"

            # Verify pod exists and is running
            pod = k8s_client.read_namespaced_pod(
                name=pod_name,
                namespace=SANDBOX_NAMESPACE,
            )
            assert pod is not None
            assert pod.status.phase == "Running"

            # Verify service exists
            service = k8s_client.read_namespaced_service(
                name=service_name,
                namespace=SANDBOX_NAMESPACE,
            )
            assert service is not None
            assert service.spec.type == "ClusterIP"

            # Verify configmap exists
            configmap = k8s_client.read_namespaced_config_map(
                name=configmap_name,
                namespace=SANDBOX_NAMESPACE,
            )
            assert configmap is not None
            assert "AGENTS.md" in configmap.data

    finally:
        # Clean up: terminate the sandbox
        if sandbox_id and session_id:
            with get_session_with_current_tenant() as db_session:
                manager.terminate(sandbox_id, db_session)

            # Verify Kubernetes resources are cleaned up
            k8s_client = _get_kubernetes_client()
            pod_name = f"sandbox-{session_id[:8]}"

            # Give K8s a moment to delete resources
            time.sleep(2)

            # Verify pod is deleted (or being deleted)
            try:
                pod = k8s_client.read_namespaced_pod(
                    name=pod_name,
                    namespace=SANDBOX_NAMESPACE,
                )
                # Pod might still exist but be terminating
                assert pod.metadata.deletion_timestamp is not None
            except ApiException as e:
                # 404 means pod was successfully deleted
                assert e.status == 404
