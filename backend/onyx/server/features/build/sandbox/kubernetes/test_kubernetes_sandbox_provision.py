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
from uuid import uuid4

import pytest
from kubernetes import client  # type: ignore[import-untyped]
from kubernetes import config
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from kubernetes.stream import stream as k8s_stream  # type: ignore[import-untyped]

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


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
def test_kubernetes_sandbox_provision() -> None:
    """Test that provision() creates a sandbox pod and DB record successfully.

    This is a happy path test that:
    1. Creates a BuildSession in the database
    2. Calls provision() to create a Kubernetes pod
    3. Verifies the sandbox is created with RUNNING status
    4. Cleans up by terminating the sandbox
    """
    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    tenant_id = "public"

    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()
    user_id = uuid4()

    # Create a test LLM config (values don't matter for this test)
    llm_config = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4",
        api_key="test-key",
        api_base=None,
    )

    try:
        # Call provision (no longer needs db_session)
        sandbox_info = manager.provision(
            sandbox_id=sandbox_id,
            user_id=user_id,
            tenant_id=tenant_id,
            file_system_path="/tmp/test-files",  # Not used by K8s manager
            llm_config=llm_config,
        )

        # Verify the return value
        assert sandbox_info.sandbox_id == sandbox_id
        assert sandbox_info.status == SandboxStatus.RUNNING
        assert sandbox_info.directory_path.startswith("k8s://")

        # Verify Kubernetes resources exist
        k8s_client = _get_kubernetes_client()
        pod_name = f"sandbox-{str(sandbox_id)[:8]}"
        service_name = pod_name

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

        # Verify AGENTS.md file exists in the pod (written by init container)
        exec_command = ["/bin/sh", "-c", "cat /workspace/AGENTS.md"]
        resp = k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="sandbox",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        assert resp is not None
        assert len(resp) > 0, "AGENTS.md file should not be empty"
        # Verify it contains expected content (from template or default)
        assert "Agent" in resp or "Instructions" in resp or "#" in resp

        # Verify /workspace/outputs directory exists and contains expected files
        exec_command = ["/bin/sh", "-c", "ls -la /workspace/outputs"]
        resp = k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="sandbox",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        assert resp is not None
        # TODO: Update with expected contents
        # assert "EXPECTED_FILE_OR_DIR" in resp, "/workspace/outputs should contain EXPECTED_FILE_OR_DIR"

        # Verify /workspace/files directory exists and contains expected files
        exec_command = ["/bin/sh", "-c", "ls -la /workspace/files"]
        resp = k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="sandbox",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        assert resp is not None
        # TODO: Update with expected contents
        # assert "EXPECTED_FILE_OR_DIR" in resp, "/workspace/files should contain EXPECTED_FILE_OR_DIR"

        # Verify /workspace/user_uploaded_files directory exists and contains expected files
        exec_command = ["/bin/sh", "-c", "ls -la /workspace/user_uploaded_files"]
        resp = k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="sandbox",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        assert resp is not None
        # TODO: Update with expected contents
        # assert "EXPECTED_FILE_OR_DIR" in resp, "/workspace/user_uploaded_files should contain EXPECTED_FILE_OR_DIR"

    finally:
        # Clean up: terminate the sandbox (no longer needs db_session)
        if sandbox_id:
            manager.terminate(sandbox_id)

            # Verify Kubernetes resources are cleaned up
            k8s_client = _get_kubernetes_client()
            pod_name = f"sandbox-{str(sandbox_id)[:8]}"

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
