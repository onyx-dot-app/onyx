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
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.base import ACPEvent
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# Test constants
TEST_TENANT_ID = "test-tenant"
TEST_USER_ID = UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c")


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
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()

    # Create a test LLM config (values don't matter for this test)
    llm_config = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4",
        api_key="test-key",
        api_base=None,
    )

    try:
        # Call provision
        sandbox_info = manager.provision(
            sandbox_id=sandbox_id,
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
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

        # Verify /workspace/templates/outputs directory exists and contains expected files
        exec_command = ["/bin/sh", "-c", "ls -la /workspace/templates/outputs"]
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
        print(f"DEBUG: Contents of /workspace/templates/outputs:\n{resp}")
        assert (
            "web" in resp
        ), f"/workspace/templates/outputs should contain web directory. Actual contents:\n{resp}"

        # Verify /workspace/templates/outputs/web/AGENTS.md file exists
        exec_command = [
            "/bin/sh",
            "-c",
            "cat /workspace/templates/outputs/web/AGENTS.md",
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
        assert (
            len(resp) > 0
        ), "/workspace/templates/outputs/web/AGENTS.md file should not be empty"
        # Verify it contains expected content
        assert (
            "Agent" in resp or "Instructions" in resp or "#" in resp
        ), "/workspace/templates/outputs/web/AGENTS.md should contain agent instructions"

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

        # start session
        session_id = uuid4()
        manager.setup_session_workspace(
            sandbox_id=sandbox_id,
            session_id=session_id,
            llm_config=llm_config,
            nextjs_port=SANDBOX_NEXTJS_PORT_START,
            file_system_path=None,
            snapshot_path=None,
            user_name="Test User",
            user_role="Test Role",
        )

        # Verify AGENTS.md file exists for the session
        exec_command = [
            "/bin/sh",
            "-c",
            f"cat /workspace/sessions/{session_id}/AGENTS.md",
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
        assert len(resp) > 0, "AGENTS.md file should not be empty"
        # Verify it contains expected content (from template or default)
        assert "Agent" in resp or "Instructions" in resp or "#" in resp
        assert "Test User" in resp
        assert "Test Role" in resp

        # Verify opencode.json file exists for the session
        exec_command = [
            "/bin/sh",
            "-c",
            f"cat /workspace/sessions/{session_id}/opencode.json",
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
        assert len(resp) > 0, "opencode.json file should not be empty"

        # verify that the outputs directory is copied over
        exec_command = [
            "/bin/sh",
            "-c",
            f"ls -la /workspace/sessions/{session_id}/outputs",
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
        assert len(resp) > 0, "outputs directory should not be empty"
        assert "web" in resp, "outputs directory should contain web directory"

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

    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()
    session_id = uuid4()

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
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
            llm_config=llm_config,
        )

        assert sandbox_info.status == SandboxStatus.RUNNING

        # Verify health check passes before sending message
        is_healthy = False
        for _ in range(10):
            is_healthy = manager.health_check(sandbox_id)
            if is_healthy:
                break
            time.sleep(10)

        assert is_healthy, "Sandbox agent should be healthy before sending messages"
        print("DEBUG: Sandbox agent is healthy")

        manager.setup_session_workspace(
            sandbox_id, session_id, llm_config, nextjs_port=SANDBOX_NEXTJS_PORT_START
        )

        # Send a simple message
        events: list[ACPEvent] = []
        for event in manager.send_message(sandbox_id, session_id, "What is 2 + 2?"):
            events.append(event)

        # Verify we received events
        assert len(events) > 0, "Should receive at least one event from send_message"

        for event in events:
            print(f"Recieved event: {event}")

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


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_kubernetes_sandbox_webapp_passthrough() -> None:
    """Test that the webapp passthrough (Next.js server) is accessible in the sandbox.

    This test:
    1. Creates a sandbox pod
    2. Sets up a session workspace
    3. Verifies the Next.js server is running and accessible within the pod
    4. Verifies get_nextjs_url returns the correct cluster URL format
    5. Cleans up by terminating the sandbox
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()
    session_id = uuid4()

    # Create a test LLM config
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
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
            llm_config=llm_config,
        )

        assert sandbox_info.status == SandboxStatus.RUNNING

        # Verify health check passes before testing webapp
        is_healthy = False
        for _ in range(10):
            is_healthy = manager.health_check(sandbox_id)
            if is_healthy:
                break
            time.sleep(10)

        assert is_healthy, "Sandbox should be healthy before testing webapp passthrough"
        print("DEBUG: Sandbox is healthy")

        # Set up session workspace
        manager.setup_session_workspace(
            sandbox_id=sandbox_id,
            session_id=session_id,
            llm_config=llm_config,
            nextjs_port=SANDBOX_NEXTJS_PORT_START,
            file_system_path=None,
            snapshot_path=None,
            user_name="Test User",
            user_role="Test Role",
        )

        # Get Kubernetes client for exec operations
        k8s_client = _get_kubernetes_client()
        pod_name = f"sandbox-{str(sandbox_id)[:8]}"

        # Wait for Next.js server to be ready (it may take a few seconds to start)
        # The session uses the first port in the configured range
        test_nextjs_port = SANDBOX_NEXTJS_PORT_START
        nextjs_ready = False
        for attempt in range(30):
            exec_command = [
                "/bin/sh",
                "-c",
                (
                    f"curl -s -o /dev/null -w '%{{http_code}}' "
                    f"http://localhost:{test_nextjs_port}/ 2>/dev/null || echo 'failed'"
                ),
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
            print(f"DEBUG: Next.js health check attempt {attempt + 1}: {resp}")
            if resp and resp.strip() in ("200", "304"):
                nextjs_ready = True
                break
            time.sleep(2)

        assert (
            nextjs_ready
        ), f"Next.js server should be accessible at localhost:{SANDBOX_NEXTJS_PORT_START}"
        print("DEBUG: Next.js server is ready")

        # Verify we can fetch actual content from the Next.js server
        exec_command = [
            "/bin/sh",
            "-c",
            f"curl -s http://localhost:{SANDBOX_NEXTJS_PORT_START}/ | head -c 500",
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
        assert resp is not None, "Should receive content from Next.js server"
        assert len(resp) > 0, "Next.js server response should not be empty"
        # Basic check that it looks like HTML
        assert (
            "<" in resp or "html" in resp.lower() or "<!doctype" in resp.lower()
        ), f"Response should be HTML content. Got: {resp[:200]}"
        print(f"DEBUG: Next.js server returned content (first 200 chars): {resp[:200]}")

        # Verify get_nextjs_url returns correctly formatted cluster URL
        nextjs_url = manager.get_webapp_url(sandbox_id, test_nextjs_port)
        expected_service_name = f"sandbox-{str(sandbox_id)[:8]}"
        expected_url_pattern = (
            f"http://{expected_service_name}.{SANDBOX_NAMESPACE}.svc.cluster.local:"
        )
        assert nextjs_url.startswith(expected_url_pattern), (
            f"Next.js URL should follow cluster service format. "
            f"Expected to start with: {expected_url_pattern}, Got: {nextjs_url}"
        )
        assert (
            str(SANDBOX_NEXTJS_PORT_START) in nextjs_url
        ), f"Next.js URL should contain port {SANDBOX_NEXTJS_PORT_START}. Got: {nextjs_url}"
        print(f"DEBUG: get_nextjs_url returned: {nextjs_url}")

        # Verify the service is accessible via the cluster URL from within the pod
        exec_command = [
            "/bin/sh",
            "-c",
            f"curl -s -o /dev/null -w '%{{http_code}}' {nextjs_url}/ 2>/dev/null || echo 'failed'",
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
        print(f"DEBUG: Cluster URL health check response: {resp}")
        assert resp and resp.strip() in ("200", "304"), (
            f"Next.js server should be accessible via cluster URL {nextjs_url}. "
            f"Got response: {resp}"
        )

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


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_kubernetes_sandbox_file_sync() -> None:
    """Test that sync_files() triggers S3 sync in the file-sync sidecar.

    This test:
    1. Creates a sandbox pod (which now has file-sync as sidecar)
    2. Verifies the file-sync sidecar is running
    3. Calls sync_files() to trigger S3 sync
    4. Verifies the sync command executes successfully
    5. Cleans up by terminating the sandbox
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context (required for multi-tenant operations)
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    # Get the manager instance
    manager = KubernetesSandboxManager()

    sandbox_id = uuid4()

    # Create a test LLM config
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
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
            llm_config=llm_config,
        )

        assert sandbox_info.status == SandboxStatus.RUNNING

        # Verify the pod is running
        k8s_client = _get_kubernetes_client()
        pod_name = f"sandbox-{str(sandbox_id)[:8]}"
        pod = k8s_client.read_namespaced_pod(
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
        )
        assert pod is not None
        assert pod.status.phase == "Running"

        # Verify file-sync sidecar container is running
        # With sidecar model, file-sync should be a regular container (not init)
        container_statuses = pod.status.container_statuses or []
        file_sync_status = next(
            (c for c in container_statuses if c.name == "file-sync"),
            None,
        )
        assert file_sync_status is not None, "file-sync sidecar container should exist"
        assert file_sync_status.ready, "file-sync sidecar container should be ready"
        print(f"DEBUG: file-sync container status: {file_sync_status}")

        # Wipe the /workspace/files directory to ensure files we find are from the sync
        exec_command = ["/bin/sh", "-c", "rm -rf /workspace/files/*"]
        k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="file-sync",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        print("DEBUG: Wiped /workspace/files directory")

        # Verify the directory is empty
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
        file_count = int(resp.strip()) if resp else 0
        assert (
            file_count == 0
        ), f"/workspace/files should be empty before sync, found {file_count} files"
        print("DEBUG: Verified /workspace/files is empty")

        # Call sync_files() to trigger S3 sync
        result = manager.sync_files(
            sandbox_id=sandbox_id,
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
        )
        assert result is True, "sync_files() should return True on success"
        print("DEBUG: sync_files() completed successfully")

        # Verify /workspace/files exists and has files synced from S3
        # (verifies the shared volume is working and sync actually transferred files)
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
        assert resp is not None, "/workspace/files should be accessible from sandbox"
        file_count = int(resp.strip()) if resp else 0
        assert (
            file_count > 0
        ), f"sync_files() should have synced files, but found {file_count} files"
        print(f"DEBUG: sync_files() synced {file_count} files to /workspace/files")

        # Also verify we can exec into file-sync sidecar directly
        exec_command = ["/bin/sh", "-c", "ls -la /workspace/files"]
        resp = k8s_stream(
            k8s_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="file-sync",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        assert resp is not None, "/workspace/files should be accessible from file-sync"
        print(f"DEBUG: Contents of /workspace/files (from file-sync sidecar):\n{resp}")

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


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_health_check_returns_true_for_running_pod() -> None:
    """Test that health_check() returns True for a healthy, running pod.

    This test:
    1. Creates a sandbox pod
    2. Calls health_check() and verifies it returns True
    3. Cleans up by terminating the sandbox
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    manager = KubernetesSandboxManager()
    sandbox_id = uuid4()

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
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
            llm_config=llm_config,
        )

        assert sandbox_info.status == SandboxStatus.RUNNING

        # Wait for pod to be fully healthy (it may take a few seconds)
        is_healthy = False
        for _ in range(10):
            is_healthy = manager.health_check(sandbox_id, timeout=5.0)
            if is_healthy:
                break
            time.sleep(2)

        assert (
            is_healthy
        ), "health_check() should return True for a running, healthy pod"

    finally:
        if sandbox_id:
            manager.terminate(sandbox_id)


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_health_check_returns_false_for_missing_pod() -> None:
    """Test that health_check() returns False when the pod doesn't exist.

    This test:
    1. Uses a random UUID that has no corresponding pod
    2. Calls health_check() and verifies it returns False
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    manager = KubernetesSandboxManager()

    # Use a random UUID that definitely has no pod
    nonexistent_sandbox_id = uuid4()

    # health_check should return False for non-existent pod
    is_healthy = manager.health_check(nonexistent_sandbox_id, timeout=5.0)

    assert not is_healthy, "health_check() should return False for a non-existent pod"


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="SANDBOX_BACKEND must be 'kubernetes' to run this test",
)
def test_health_check_returns_false_after_termination() -> None:
    """Test that health_check() returns False after a pod has been terminated.

    This test:
    1. Creates a sandbox pod
    2. Verifies health_check() returns True
    3. Terminates the sandbox
    4. Verifies health_check() returns False
    """
    _is_kubernetes_available()

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Set up tenant context
    CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)

    manager = KubernetesSandboxManager()
    sandbox_id = uuid4()

    llm_config = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4",
        api_key="test-key",
        api_base=None,
    )

    # Provision the sandbox
    sandbox_info = manager.provision(
        sandbox_id=sandbox_id,
        user_id=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        llm_config=llm_config,
    )

    assert sandbox_info.status == SandboxStatus.RUNNING

    # Wait for pod to be fully healthy
    is_healthy = False
    for _ in range(10):
        is_healthy = manager.health_check(sandbox_id, timeout=5.0)
        if is_healthy:
            break
        time.sleep(2)

    assert is_healthy, "Pod should be healthy before termination"

    # Terminate the sandbox
    manager.terminate(sandbox_id)

    # Wait for pod to be deleted
    time.sleep(3)

    # health_check should now return False
    is_healthy_after = manager.health_check(sandbox_id, timeout=5.0)

    assert (
        not is_healthy_after
    ), "health_check() should return False after pod has been terminated"
