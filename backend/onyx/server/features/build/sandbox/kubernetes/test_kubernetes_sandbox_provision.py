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


def _is_kubernetes_available() -> None:
    """Check if Kubernetes is available and configured."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    v1 = client.CoreV1Api()
    # List pods in sandbox namespace instead of namespaces (avoids cluster-scope permissions)
    v1.list_namespaced_pod(SANDBOX_NAMESPACE, limit=1)


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
def test_kubernetes_sandbox_provision() -> None:
    """Test that provision() creates a sandbox pod and DB record successfully.

    This is a happy path test that:
    1. Creates a BuildSession in the database
    2. Calls provision() to create a Kubernetes pod
    3. Verifies the sandbox is created with RUNNING status
    4. Cleans up by terminating the sandbox
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    tenant_id = "test-tenant"

    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()
    user_id = UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c")

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
        print(f"DEBUG: Contents of /workspace/outputs:\n{resp}")
        assert (
            "web" in resp
        ), f"/workspace/outputs should contain web directory. Actual contents:\n{resp}"

        # Verify /workspace/outputs/web directory exists
        exec_command = [
            "/bin/sh",
            "-c",
            "test -d /workspace/outputs/web && echo 'exists'",
        ]
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
        assert "exists" in resp, "/workspace/outputs/web directory should exist"

        # Verify /workspace/outputs/web/AGENTS.md file exists
        exec_command = ["/bin/sh", "-c", "cat /workspace/outputs/web/AGENTS.md"]
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
        assert (
            len(resp) > 0
        ), "/workspace/outputs/web/AGENTS.md file should not be empty"
        # Verify it contains expected content
        assert (
            "Agent" in resp or "Instructions" in resp or "#" in resp
        ), "/workspace/outputs/web/AGENTS.md should contain agent instructions"

        # Verify /workspace/files directory exists and contains expected files
        exec_command = ["/bin/sh", "-c", "find /workspace/files -type f | wc -l"]
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
        file_count = int(resp.strip())
        assert (
            file_count == 1099
        ), f"/workspace/files should contain 1099 files, but found {file_count}"

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


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_kubernetes_sandbox_send_message() -> None:
    """Test that send_message() communicates with the sandbox agent successfully.

    This test:
    1. Creates a sandbox pod
    2. Sends a simple message via send_message()
    3. Verifies we receive ACP events back (agent responses)
    4. Cleans up by terminating the sandbox
    """
    from acp.schema import AgentMessageChunk
    from acp.schema import Error
    from acp.schema import PromptResponse

    from onyx.server.features.build.sandbox.kubernetes.internal.acp_http_client import (
        ACPEvent,
    )

    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    tenant_id = "test-tenant"
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()
    user_id = UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c")

    # Create a test LLM config (values don't matter for this test)
    llm_config = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4",
        api_key="test-key",
        api_base=None,
    )

    try:
        # Provision the sandbox
        sandbox_info = manager.provision(
            sandbox_id=sandbox_id,
            user_id=user_id,
            tenant_id=tenant_id,
            file_system_path="/tmp/test-files",
            llm_config=llm_config,
        )

        assert sandbox_info.status == SandboxStatus.RUNNING

        # Give the agent service time to start up
        time.sleep(5)

        # Verify health check passes before sending message
        is_healthy = manager.health_check(sandbox_id, nextjs_port=None)
        assert is_healthy, "Sandbox agent should be healthy before sending messages"
        print("DEBUG: Sandbox agent is healthy")

        # Send a simple message
        events: list[ACPEvent] = []
        for event in manager.send_message(sandbox_id, "What is 2 + 2?"):
            events.append(event)

        # Verify we received events
        assert len(events) > 0, "Should receive at least one event from send_message"

        # Check for errors
        errors = [e for e in events if isinstance(e, Error)]
        assert len(errors) == 0, f"Should not receive errors: {errors}"

        # Verify we received some agent message content or a final response
        message_chunks = [e for e in events if isinstance(e, AgentMessageChunk)]
        prompt_responses = [e for e in events if isinstance(e, PromptResponse)]

        assert (
            len(message_chunks) > 0 or len(prompt_responses) > 0
        ), "Should receive either AgentMessageChunk or PromptResponse events"

        # If we got a PromptResponse, verify it completed successfully
        if prompt_responses:
            final_response = prompt_responses[-1]
            assert (
                final_response.stop_reason is not None
            ), "PromptResponse should have a stop_reason"

    finally:
        # Clean up: terminate the sandbox
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
