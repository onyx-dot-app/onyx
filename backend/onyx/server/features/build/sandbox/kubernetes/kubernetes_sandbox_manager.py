"""Kubernetes-based sandbox manager for production deployments.

KubernetesSandboxManager provisions sandboxes as Kubernetes pods with true
container isolation. Each sandbox runs in its own pod with dedicated resources.

Key features:
- Pod-based isolation (not process-level)
- S3-based snapshots via init containers
- Cluster-native service discovery
- RBAC-controlled resource management
- User-shared sandbox model with per-session workspaces

Architecture Note (User-Shared Sandbox Model):
- One pod per user (shared across all user's sessions)
- provision() creates the pod with shared files/ directory
- setup_session_workspace() creates per-session workspace via kubectl exec
- cleanup_session_workspace() removes session workspace via kubectl exec
- terminate() destroys the entire pod (all sessions)

Directory Structure (inside pod):
    /workspace/
    ├── files/                     # SHARED - synced from S3
    └── sessions/
        ├── $session_id_1/         # Per-session workspace
        │   ├── outputs/
        │   ├── AGENTS.md
        │   └── ...
        └── $session_id_2/
            └── ...

IMPORTANT: This manager does NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).

Use get_sandbox_manager() from base.py to get the appropriate implementation.
"""

import base64
import binascii
import io
import json
import mimetypes
import os
import re
import shlex
import tarfile
import threading
import time
from collections.abc import Generator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from kubernetes import client  # type: ignore
from kubernetes import config
from kubernetes.client.rest import ApiException  # type: ignore
from kubernetes.stream import stream as k8s_stream  # type: ignore

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_FILE_SYNC_SERVICE_ACCOUNT
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SANDBOX_SERVICE_ACCOUNT_NAME
from onyx.server.features.build.s3.s3_client import build_s3_client
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client import (
    ACPEvent,
)
from onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client import (
    ACPExecClient,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.util.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_config,
)
from onyx.server.features.build.sandbox.util.persona_mapping import (
    generate_user_identity_content,
)
from onyx.server.features.build.sandbox.util.persona_mapping import get_persona_info
from onyx.server.features.build.sandbox.util.persona_mapping import ORG_INFO_AGENTS_MD
from onyx.server.features.build.sandbox.util.persona_mapping import (
    ORGANIZATION_STRUCTURE,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constants for pod configuration
# Note: Next.js ports are dynamically allocated from SANDBOX_NEXTJS_PORT_START to
# SANDBOX_NEXTJS_PORT_END range, with one port per session.
AGENT_PORT = 8081
POD_READY_TIMEOUT_SECONDS = 120
POD_READY_POLL_INTERVAL_SECONDS = 2

# Resource deletion timeout and polling interval
# Kubernetes deletes are async - we need to wait for resources to actually be gone
RESOURCE_DELETION_TIMEOUT_SECONDS = 30
RESOURCE_DELETION_POLL_INTERVAL_SECONDS = 0.5


def _build_nextjs_start_script(
    session_path: str,
    nextjs_port: int,
    check_node_modules: bool = False,
) -> str:
    """Build shell script to start the NextJS dev server.

    Args:
        session_path: Path to the session directory (should be shell-safe)
        nextjs_port: Port number for the NextJS dev server
        check_node_modules: If True, check for node_modules and run npm install if missing

    Returns:
        Shell script string to start the NextJS server
    """
    npm_install_check = ""
    if check_node_modules:
        npm_install_check = """
# Check if npm dependencies are installed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi
"""

    return f"""
set -e
cd {session_path}/outputs/web
{npm_install_check}
# Start npm run dev in background
echo "Starting Next.js dev server on port {nextjs_port}..."
nohup npm run dev -- -p {nextjs_port} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
"""


def _get_local_aws_credential_env_vars() -> list[client.V1EnvVar]:
    """Get AWS credential environment variables from local environment.

    Checks for AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and optionally
    AWS_SESSION_TOKEN and AWS_DEFAULT_REGION in the local environment.
    If credentials are found, returns V1EnvVar objects to pass them to containers.

    This allows using local AWS credentials for development/testing while
    IRSA (IAM Roles for Service Accounts) handles credentials in production EKS.

    Returns:
        List of V1EnvVar objects for AWS credentials, empty if not set locally.
    """
    env_vars: list[client.V1EnvVar] = []

    aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

    # Only add credentials if both required values are present
    if aws_access_key and aws_secret_key:
        env_vars.append(client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=aws_access_key))
        env_vars.append(
            client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=aws_secret_key)
        )

        # Optional: session token for temporary credentials
        aws_session_token = os.environ.get("AWS_SESSION_TOKEN")
        if aws_session_token:
            env_vars.append(
                client.V1EnvVar(name="AWS_SESSION_TOKEN", value=aws_session_token)
            )

        # Optional: default region
        aws_region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get(
            "AWS_REGION"
        )
        if aws_region:
            env_vars.append(
                client.V1EnvVar(name="AWS_DEFAULT_REGION", value=aws_region)
            )

        logger.info("Using local AWS credentials for sandbox init container")

    return env_vars


class KubernetesSandboxManager(SandboxManager):
    """Kubernetes-based sandbox manager for production deployments.

    Manages sandboxes as Kubernetes pods with:
    - Init containers for S3 file sync (snapshots, knowledge files, uploads)
    - Main sandbox container running Next.js + opencode agent
    - ClusterIP services for network access

    IMPORTANT: This manager does NOT interface with the database directly.
    All database operations should be handled by the caller.

    This is a singleton class - use get_sandbox_manager() to get the instance.
    """

    _instance: "KubernetesSandboxManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "KubernetesSandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize Kubernetes client and configuration."""
        # Load Kubernetes config (in-cluster or kubeconfig)
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig from default location")
            except config.ConfigException as e:
                raise RuntimeError(
                    f"Failed to load Kubernetes configuration: {e}"
                ) from e

        # IMPORTANT: We use separate ApiClient instances for REST vs streaming operations.
        # The kubernetes.stream.stream function monkey-patches the ApiClient's request
        # method to use WebSocket. If we share the same ApiClient for both REST and
        # streaming, the patching can leak, causing REST calls to erroneously use
        # WebSocket (resulting in "Handshake status 200 OK" errors).
        self._rest_api_client = client.ApiClient()
        self._stream_api_client = client.ApiClient()

        # Use the REST client for standard CRUD operations
        self._core_api = client.CoreV1Api(api_client=self._rest_api_client)
        self._batch_api = client.BatchV1Api(api_client=self._rest_api_client)
        self._networking_api = client.NetworkingV1Api(api_client=self._rest_api_client)

        # Use a separate client for streaming/exec operations
        self._stream_core_api = client.CoreV1Api(api_client=self._stream_api_client)

        self._namespace = SANDBOX_NAMESPACE
        self._image = SANDBOX_CONTAINER_IMAGE
        self._s3_bucket = SANDBOX_S3_BUCKET
        self._service_account = SANDBOX_SERVICE_ACCOUNT_NAME
        self._file_sync_service_account = SANDBOX_FILE_SYNC_SERVICE_ACCOUNT

        # Load AGENTS.md template path
        build_dir = Path(__file__).parent.parent.parent  # /onyx/server/features/build/
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"
        self._skills_path = build_dir / "skills"

        logger.info(
            f"KubernetesSandboxManager initialized: "
            f"namespace={self._namespace}, image={self._image}"
        )

    def _get_pod_name(self, sandbox_id: str) -> str:
        """Generate pod name from sandbox ID."""
        return f"sandbox-{str(sandbox_id)[:8]}"

    def _get_service_name(self, sandbox_id: str) -> str:
        """Generate service name from sandbox ID."""
        return self._get_pod_name(sandbox_id)

    def _get_nextjs_url(self, sandbox_id: str, port: int) -> str:
        """Get the internal cluster URL for a session's Next.js server.

        Args:
            sandbox_id: The sandbox ID (string)
            port: The session's allocated Next.js port

        Returns:
            Internal cluster URL for the Next.js server on the specified port
        """
        service_name = self._get_service_name(sandbox_id)
        return f"http://{service_name}.{self._namespace}.svc.cluster.local:{port}"

    def _load_agent_instructions(
        self,
        provider: str | None = None,
        model_name: str | None = None,
        nextjs_port: int | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
        use_demo_data: bool = False,
        include_org_info: bool = False,
    ) -> str:
        """Load and populate agent instructions from template file.

        Args:
            provider: LLM provider type
            model_name: Model name
            nextjs_port: Next.js port
            disabled_tools: List of disabled tools
            user_name: User's name for personalization
            user_role: User's role/title for personalization
            use_demo_data: If True, exclude user context from AGENTS.md
            include_org_info: Whether to include the org_info section (demo data mode)

        Returns:
            Populated agent instructions content

        Note:
            files_path is not passed here because in Kubernetes, the files are
            synced via an init container after pod creation. The agent will
            discover the file structure at runtime by exploring the files/ directory.
        """
        return generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_path=self._skills_path,
            files_path=None,  # Files are synced after pod creation
            attachments_path=None,  # Attachments won't exist until session workspace is created
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port,
            disabled_tools=disabled_tools,
            user_name=user_name,
            user_role=user_role,
            use_demo_data=use_demo_data,
            include_org_info=include_org_info,
        )

    def _create_sandbox_pod(
        self,
        sandbox_id: str,
        user_id: str,
        tenant_id: str,
    ) -> client.V1Pod:
        """Create Pod specification for sandbox (user-level).

        Creates pod with:
        - files/ directory synced from S3 (shared across sessions)
        - sessions/ directory for per-session workspaces

        NOTE: Session-specific setup is done via setup_session_workspace().
        """
        pod_name = self._get_pod_name(sandbox_id)

        # File-sync sidecar container for S3 file sync (knowledge files only)
        # Runs as sidecar (not init container) so we can trigger incremental syncs
        # via kubectl exec after new documents are indexed
        file_sync_container = client.V1Container(
            name="file-sync",
            image="amazon/aws-cli:latest",
            env=_get_local_aws_credential_env_vars()
            + [
                # Set HOME to a writable directory so AWS CLI can create .aws config dir
                # Without this, AWS CLI tries to access /.aws which fails with permission denied
                client.V1EnvVar(name="HOME", value="/tmp"),
            ],
            command=["/bin/sh", "-c"],
            args=[
                f"""
set -e

# Handle SIGTERM for fast container termination
trap 'echo "Received SIGTERM, exiting"; exit 0' TERM

# Initial sync on startup - sync knowledge files for this user/tenant
echo "Starting initial file sync for tenant: {tenant_id} / user: {user_id}"
aws s3 sync "s3://{self._s3_bucket}/{tenant_id}/knowledge/{user_id}/" /workspace/files/

echo "Initial sync complete, staying alive for incremental syncs"
# Stay alive - incremental sync commands will be executed via kubectl exec
# Use 'wait' so shell can respond to signals while sleeping
while true; do
    sleep 30 &
    wait $!
done
"""
            ],
            volume_mounts=[
                client.V1VolumeMount(name="files", mount_path="/workspace/files"),
            ],
            resources=client.V1ResourceRequirements(
                # Reduced resources since sidecar is mostly idle (sleeping)
                requests={"cpu": "50m", "memory": "128Mi"},
                limits={"cpu": "1000m", "memory": "1Gi"},
            ),
        )

        # Main sandbox container
        # Note: Container ports are informational only in K8s. Each session's Next.js
        # server binds to its allocated port from the SANDBOX_NEXTJS_PORT_START-END range.
        # We declare all ports for documentation, tooling, and network policies.
        container_ports = [
            client.V1ContainerPort(name="agent", container_port=AGENT_PORT),
        ]
        # Add ports for session Next.js servers (one port per potential session)
        for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
            container_ports.append(
                client.V1ContainerPort(
                    name=f"nextjs-{port}",
                    container_port=port,
                )
            )

        sandbox_container = client.V1Container(
            name="sandbox",
            image=self._image,
            image_pull_policy="IfNotPresent",
            ports=container_ports,
            volume_mounts=[
                client.V1VolumeMount(
                    name="files", mount_path="/workspace/files", read_only=True
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "500m", "memory": "1Gi"},
                limits={"cpu": "2000m", "memory": "6Gi"},
            ),
            # TODO: Re-enable probes when sandbox container runs actual services.
            # Note: Next.js ports are now per-session (dynamic), so container-level
            # probes would need to check the agent port or use a different approach.
            # liveness_probe=client.V1Probe(
            #     http_get=client.V1HTTPGetAction(path="/global/health", port=AGENT_PORT),
            #     initial_delay_seconds=30,
            #     period_seconds=30,
            #     timeout_seconds=5,
            #     failure_threshold=3,
            # ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=False,
                privileged=False,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )

        # Volumes - workspace holds sessions/, files is shared read-only
        volumes = [
            client.V1Volume(
                name="workspace",
                # Increased size: holds sessions/ directory with per-session outputs
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="50Gi"),
            ),
            client.V1Volume(
                name="files",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="5Gi"),
            ),
        ]

        # Pod spec
        # Note: file_sync_container runs as sidecar (not init container) so we can
        # trigger incremental S3 syncs via kubectl exec after new documents are indexed
        pod_spec = client.V1PodSpec(
            service_account_name=self._file_sync_service_account,
            containers=[sandbox_container, file_sync_container],
            volumes=volumes,
            restart_policy="Never",
            termination_grace_period_seconds=10,  # Fast pod termination
            # CRITICAL: Disable service environment variable injection
            # Without this, Kubernetes injects env vars for ALL services in the namespace,
            # which can exceed ARG_MAX (2.6MB) when there are many sandbox pods.
            # With 40+ sandboxes × 100 ports × 4 env vars each = ~16k env vars (~2.2MB)
            # This causes "exec /bin/sh: argument list too long" errors.
            enable_service_links=False,
            # Node selection for sandbox nodes
            node_selector={"onyx.app/workload": "sandbox"},
            tolerations=[
                client.V1Toleration(
                    key="workload",
                    operator="Equal",
                    value="sandbox",
                    effect="NoSchedule",
                ),
            ],
            # Security context for pod
            security_context=client.V1PodSecurityContext(
                run_as_non_root=True,
                run_as_user=1000,
                fs_group=1000,
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
            # Disable host access
            host_network=False,
            host_pid=False,
            host_ipc=False,
        )

        return client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "sandbox",
                    "app.kubernetes.io/managed-by": "onyx",
                    "onyx.app/sandbox-id": sandbox_id,
                    "onyx.app/tenant-id": tenant_id,
                },
            ),
            spec=pod_spec,
        )

    def _create_sandbox_service(
        self,
        sandbox_id: UUID,
        tenant_id: str,
    ) -> client.V1Service:
        """Create ClusterIP Service for sandbox pod.

        Exposes the agent port and a range of ports for per-session Next.js servers.
        The port range matches SANDBOX_NEXTJS_PORT_START to SANDBOX_NEXTJS_PORT_END.
        """
        # Convert UUID objects to strings if needed (Kubernetes client requires strings)
        sandbox_id_str: str = str(sandbox_id)
        tenant_id_str: str = str(tenant_id)

        service_name = self._get_service_name(sandbox_id_str)

        # Build port list: agent port + all session Next.js ports
        ports = [
            client.V1ServicePort(name="agent", port=AGENT_PORT, target_port=AGENT_PORT),
        ]

        # Add ports for session Next.js servers (one port per potential session)
        for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
            ports.append(
                client.V1ServicePort(
                    name=f"nextjs-{port}",
                    port=port,
                    target_port=port,
                )
            )

        return client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "sandbox",
                    "app.kubernetes.io/managed-by": "onyx",
                    "onyx.app/sandbox-id": sandbox_id_str,
                    "onyx.app/tenant-id": tenant_id_str,
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"onyx.app/sandbox-id": sandbox_id_str},
                ports=ports,
            ),
        )

    def _get_init_container_logs(self, pod_name: str, container_name: str) -> str:
        """Get logs from an init container.

        Args:
            pod_name: Name of the pod
            container_name: Name of the init container

        Returns:
            Log output from the init container, or error message if logs cannot be retrieved
        """
        try:
            logs = self._core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self._namespace,
                container=container_name,
                tail_lines=100,  # Get last 100 lines
            )
            return logs if logs else "(no logs available)"
        except ApiException as e:
            return f"(failed to retrieve logs: {e})"

    def _check_init_container_status(self, pod: client.V1Pod) -> str | None:
        """Check if any init containers have failed.

        Args:
            pod: The pod object

        Returns:
            Error message if an init container failed, None otherwise
        """
        if not pod.status.init_container_statuses:
            return None

        for init_status in pod.status.init_container_statuses:
            if init_status.state:
                # Check for terminated state with non-zero exit code
                if init_status.state.terminated:
                    if init_status.state.terminated.exit_code != 0:
                        container_name = init_status.name
                        logs = self._get_init_container_logs(
                            pod.metadata.name, container_name
                        )
                        return (
                            f"Init container '{container_name}' failed with exit code "
                            f"{init_status.state.terminated.exit_code}. "
                            f"Logs:\n{logs}"
                        )
                # Check for waiting state with error reason
                elif init_status.state.waiting:
                    if init_status.state.waiting.reason in [
                        "Error",
                        "CrashLoopBackOff",
                    ]:
                        container_name = init_status.name
                        reason = init_status.state.waiting.reason
                        message = init_status.state.waiting.message or ""
                        return (
                            f"Init container '{container_name}' is in '{reason}' state. "
                            f"Message: {message}"
                        )

        return None

    def _wait_for_pod_ready(
        self,
        pod_name: str,
        timeout: float = POD_READY_TIMEOUT_SECONDS,
    ) -> bool:
        """Wait for pod to become ready.

        Args:
            pod_name: Name of the pod to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if pod is ready, False if timeout

        Raises:
            RuntimeError: If pod fails or is deleted
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=pod_name,
                    namespace=self._namespace,
                )

                # Check init container status first (they run before main container)
                init_error = self._check_init_container_status(pod)
                if init_error:
                    raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")

                phase = pod.status.phase

                # Check for failure conditions
                if phase == "Failed":
                    # Try to get more details about the failure
                    init_error = self._check_init_container_status(pod)
                    error_msg = f"Pod {pod_name} failed to start"
                    if init_error:
                        error_msg += f": {init_error}"
                    raise RuntimeError(error_msg)

                if phase == "Succeeded":
                    raise RuntimeError(
                        f"Pod {pod_name} completed unexpectedly "
                        "(sandbox pods should run indefinitely)"
                    )

                # Check if running and ready
                if phase == "Running":
                    conditions = pod.status.conditions or []
                    for condition in conditions:
                        if condition.type == "Ready" and condition.status == "True":
                            logger.info(f"Pod {pod_name} is ready")
                            return True

                logger.debug(f"Pod {pod_name} status: {phase}, waiting...")

            except ApiException as e:
                if e.status == 404:
                    raise RuntimeError(f"Pod {pod_name} was deleted")
                logger.warning(f"Error checking pod status: {e}")

            time.sleep(POD_READY_POLL_INTERVAL_SECONDS)

        # On timeout, check one more time for init container failures
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            init_error = self._check_init_container_status(pod)
            if init_error:
                raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")
        except ApiException:
            pass  # Pod might be deleted, ignore

        logger.warning(f"Timeout waiting for pod {pod_name} to become ready")
        return False

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,
    ) -> SandboxInfo:
        """Provision a new sandbox as a Kubernetes pod (user-level).

        Creates pod with:
        1. Init container syncs files/ from S3
        2. Creates sessions/ directory for per-session workspaces
        3. Main container runs the sandbox environment

        NOTE: This does NOT set up session-specific workspaces.
        Call setup_session_workspace() to create session workspaces.

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            llm_config: LLM provider configuration

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        logger.info(
            f"Starting Kubernetes sandbox provisioning for sandbox {sandbox_id}, "
            f"user {user_id}, tenant {tenant_id}"
        )

        pod_name = self._get_pod_name(str(sandbox_id))

        try:
            # 1. Create Pod (user-level only, no session setup)
            logger.debug(f"Creating Pod {pod_name}")
            pod = self._create_sandbox_pod(
                sandbox_id=str(sandbox_id),
                user_id=str(user_id),
                tenant_id=tenant_id,
            )
            self._core_api.create_namespaced_pod(
                namespace=self._namespace,
                body=pod,
            )

            # 2. Create Service
            logger.debug(f"Creating Service {self._get_service_name(str(sandbox_id))}")
            service = self._create_sandbox_service(sandbox_id, tenant_id)
            self._core_api.create_namespaced_service(
                namespace=self._namespace,
                body=service,
            )

            # 3. Wait for pod to be ready
            logger.info(f"Waiting for pod {pod_name} to become ready...")
            if not self._wait_for_pod_ready(pod_name):
                raise RuntimeError(
                    f"Timeout waiting for sandbox pod {pod_name} to become ready"
                )

            logger.info(
                f"Provisioned Kubernetes sandbox {sandbox_id}, pod: {pod_name} "
                "(no sessions yet)"
            )

            return SandboxInfo(
                sandbox_id=sandbox_id,
                directory_path=f"k8s://{self._namespace}/{pod_name}",
                status=SandboxStatus.RUNNING,
                last_heartbeat=None,
            )

        except Exception as e:
            # Cleanup on failure
            logger.error(
                f"Kubernetes sandbox provisioning failed for sandbox {sandbox_id}: {e}",
                exc_info=True,
            )
            self._cleanup_kubernetes_resources(str(sandbox_id))
            raise

    def _wait_for_resource_deletion(
        self,
        resource_type: str,
        name: str,
        timeout: float = RESOURCE_DELETION_TIMEOUT_SECONDS,
    ) -> bool:
        """Wait for a Kubernetes resource to be fully deleted.

        Kubernetes delete calls are asynchronous - the API returns immediately
        but the resource may still exist in a 'Terminating' state. This method
        polls until the resource returns 404 (not found).

        Args:
            resource_type: Type of resource ("pod" or "service")
            name: Name of the resource
            timeout: Maximum time to wait in seconds

        Returns:
            True if resource was deleted, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                if resource_type == "pod":
                    self._core_api.read_namespaced_pod(
                        name=name,
                        namespace=self._namespace,
                    )
                elif resource_type == "service":
                    self._core_api.read_namespaced_service(
                        name=name,
                        namespace=self._namespace,
                    )
                else:
                    raise ValueError(f"Unknown resource type: {resource_type}")

                # Resource still exists, wait and retry
                logger.debug(f"Waiting for {resource_type} {name} to be deleted...")
                time.sleep(RESOURCE_DELETION_POLL_INTERVAL_SECONDS)

            except ApiException as e:
                if e.status == 404:
                    # Resource is gone
                    logger.debug(f"{resource_type.capitalize()} {name} fully deleted")
                    return True
                # Other error, log and continue waiting
                logger.warning(f"Error checking {resource_type} {name} status: {e}")
                time.sleep(RESOURCE_DELETION_POLL_INTERVAL_SECONDS)

        logger.warning(
            f"Timeout waiting for {resource_type} {name} to be deleted "
            f"after {timeout}s"
        )
        return False

    def _cleanup_kubernetes_resources(
        self,
        sandbox_id: str,
        wait_for_deletion: bool = True,
    ) -> None:
        """Clean up Kubernetes resources for a sandbox.

        Args:
            sandbox_id: The sandbox ID to clean up
            wait_for_deletion: If True, wait for resources to be fully deleted
                before returning. This prevents 409 conflicts when immediately
                re-provisioning with the same sandbox ID.
        """
        # Convert UUID objects to strings if needed (Kubernetes client requires strings)
        sandbox_id = str(sandbox_id)

        pod_name = self._get_pod_name(sandbox_id)
        service_name = self._get_service_name(sandbox_id)

        # Delete in reverse order of creation
        service_deleted = False
        try:
            self._core_api.delete_namespaced_service(
                name=service_name,
                namespace=self._namespace,
            )
            logger.debug(f"Deleted Service {service_name}")
            service_deleted = True
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                service_deleted = True
            else:
                logger.warning(f"Error deleting Service {service_name}: {e}")

        pod_deleted = False
        try:
            self._core_api.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            logger.debug(f"Deleted Pod {pod_name}")
            pod_deleted = True
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                pod_deleted = True
            else:
                logger.warning(f"Error deleting Pod {pod_name}: {e}")

        # Wait for resources to be fully deleted to prevent 409 conflicts
        # on immediate re-provisioning
        if wait_for_deletion:
            if service_deleted:
                self._wait_for_resource_deletion("service", service_name)
            if pod_deleted:
                self._wait_for_resource_deletion("pod", pod_name)

    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up Kubernetes resources.

        Deletes the Service and Pod for the sandbox.

        Args:
            sandbox_id: The sandbox ID to terminate
        """
        # Clean up Kubernetes resources (needs string for pod/service names)
        self._cleanup_kubernetes_resources(str(sandbox_id))

        logger.info(f"Terminated Kubernetes sandbox {sandbox_id}")

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int,
        file_system_path: str | None = None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
        user_work_area: str | None = None,
        user_level: str | None = None,
        use_demo_data: bool = False,
    ) -> None:
        """Set up a session workspace within an existing sandbox pod.

        Executes kubectl exec to:
        1. Create sessions/$session_id/ directory
        2. Create files/ symlink (to demo data or S3-synced user files)
        3. Copy outputs template from local templates (downloaded during init)
        4. Write AGENTS.md
        5. Write opencode.json with LLM config
        6. Create org_info/ directory with user identity file (if demo data enabled)
        7. Start Next.js dev server

        Note: Snapshot restoration is not supported in Kubernetes mode since the
        main container doesn't have S3 access. Snapshots would need to be
        pre-downloaded during pod provisioning if needed.

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            file_system_path: Path to user's S3-synced knowledge files (/workspace/files)
            snapshot_path: Optional S3 path - logged but ignored (no S3 access)
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md
            user_work_area: User's work area for demo persona (e.g., "engineering")
            user_level: User's level for demo persona (e.g., "ic", "manager")
            use_demo_data: If True, symlink files/ to /workspace/demo_data;
                          else to /workspace/files (S3-synced user files)

        Raises:
            RuntimeError: If workspace setup fails
        """
        if snapshot_path:
            logger.warning(
                f"Snapshot restoration requested but not supported in Kubernetes mode. "
                f"Snapshot path {snapshot_path} will be ignored. "
                f"Session {session_id} will start with fresh outputs template."
            )

        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        agent_instructions = self._load_agent_instructions(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
            user_role=user_role,
            use_demo_data=use_demo_data,
            include_org_info=use_demo_data,
        )

        # Build opencode config JSON using shared config builder
        opencode_config = build_opencode_config(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            api_key=llm_config.api_key if llm_config.api_key else None,
            api_base=llm_config.api_base,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
        )

        opencode_json = json.dumps(opencode_config)
        # Escape for shell
        opencode_json_escaped = opencode_json.replace("'", "'\\''")
        agent_instructions_escaped = agent_instructions.replace("'", "'\\''")

        # Build org_info setup script if persona is set
        # Uses shared constants from persona_mapping module as single source of truth
        org_info_setup = ""
        if user_work_area:
            persona = get_persona_info(user_work_area, user_level)
            if persona:
                # Escape content for shell (single quotes)
                agents_md_escaped = ORG_INFO_AGENTS_MD.replace("'", "'\\''")
                identity_escaped = generate_user_identity_content(persona).replace(
                    "'", "'\\''"
                )
                org_structure_escaped = json.dumps(
                    ORGANIZATION_STRUCTURE, indent=2
                ).replace("'", "'\\''")

                org_info_setup = f"""
# Create org_info directory with all files
mkdir -p {session_path}/org_info
printf '%s' '{agents_md_escaped}' > {session_path}/org_info/AGENTS.md
printf '%s' '{identity_escaped}' > {session_path}/org_info/user_identity_profile.txt
printf '%s' '{org_structure_escaped}' > {session_path}/org_info/organization_structure.json
"""

        # Build files symlink setup
        # Choose between demo data (baked in image) or user's S3-synced files
        if use_demo_data:
            # Demo mode: symlink to demo data baked into the container image
            symlink_target = "/workspace/demo_data"
            files_symlink_setup = f"""
# Create files symlink to demo data (baked into image)
echo "Creating files symlink to demo data: {symlink_target}"
ln -sf {symlink_target} {session_path}/files
"""
        else:
            # Normal mode: symlink to user's S3-synced knowledge files
            symlink_target = "/workspace/files"
            files_symlink_setup = f"""
# Create files symlink to user's knowledge files (synced from S3)
echo "Creating files symlink to user files: {symlink_target}"
ln -sf {symlink_target} {session_path}/files
"""

        # Copy outputs template from baked-in location and install npm dependencies
        outputs_setup = f"""
# Copy outputs template (baked into image at build time)
echo "Copying outputs template"
if [ -d /workspace/templates/outputs ]; then
    cp -r /workspace/templates/outputs/* {session_path}/outputs/
    # Install npm dependencies
    echo "Installing npm dependencies..."
    cd {session_path}/outputs/web && npm install
else
    echo "Warning: outputs template not found at /workspace/templates/outputs"
    mkdir -p {session_path}/outputs/web
fi
"""

        # Build NextJS startup script (npm install already done in outputs_setup)
        nextjs_start_script = _build_nextjs_start_script(
            session_path, nextjs_port, check_node_modules=False
        )

        setup_script = f"""
set -e

# Create session directory structure
echo "Creating session directory: {session_path}"
mkdir -p {session_path}/outputs
mkdir -p {session_path}/attachments
{files_symlink_setup}
# Setup outputs
{outputs_setup}

# Write agent instructions
echo "Writing AGENTS.md"
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md

# Write opencode config
echo "Writing opencode.json"
printf '%s' '{opencode_json_escaped}' > {session_path}/opencode.json
{org_info_setup}
# Start Next.js dev server
{nextjs_start_script}

echo "Session workspace setup complete"
"""

        logger.info(
            f"Setting up session workspace {session_id} in sandbox {sandbox_id}"
        )

        try:
            # Execute setup script in the pod
            exec_response = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                command=["/bin/sh", "-c", setup_script],
                container="sandbox",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            logger.debug(f"Session setup output: {exec_response}")
            logger.info(
                f"Set up session workspace {session_id} in sandbox {sandbox_id}"
            )

        except Exception as e:
            logger.error(
                f"Failed to setup session workspace {session_id} in sandbox {sandbox_id}: {e}",
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to setup session workspace {session_id}: {e}"
            ) from e

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,
    ) -> None:
        """Clean up a session workspace (on session delete).

        Executes kubectl exec to remove the session directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
            nextjs_port: Optional port where Next.js server is running (unused in K8s,
                        we use PID file instead)
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        cleanup_script = f"""
set -e

# Kill Next.js server if running
if [ -f {session_path}/nextjs.pid ]; then
    NEXTJS_PID=$(cat {session_path}/nextjs.pid)
    echo "Stopping Next.js server (PID: $NEXTJS_PID)"
    kill $NEXTJS_PID 2>/dev/null || true
fi

echo "Removing session directory: {session_path}"
rm -rf {session_path}
echo "Session cleanup complete"
"""

        logger.info(
            f"Cleaning up session workspace {session_id} in sandbox {sandbox_id}"
        )

        try:
            exec_response = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                command=["/bin/sh", "-c", cleanup_script],
                container="sandbox",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            logger.debug(f"Session cleanup output: {exec_response}")
            logger.info(
                f"Cleaned up session workspace {session_id} in sandbox {sandbox_id}"
            )

        except ApiException as e:
            if e.status == 404:
                # Pod not found, nothing to clean up
                logger.debug(f"Pod {pod_name} not found, skipping cleanup")
            else:
                logger.warning(f"Error cleaning up session workspace {session_id}: {e}")
        except Exception as e:
            logger.warning(f"Error cleaning up session workspace {session_id}: {e}")

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        """Create a snapshot of a session's outputs directory.

        For Kubernetes backend, we exec into the pod to create the snapshot.
        Only captures sessions/$session_id/outputs/

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size

        Raises:
            RuntimeError: If snapshot creation fails
        """
        sandbox_id_str = str(sandbox_id)
        session_id_str = str(session_id)
        pod_name = self._get_pod_name(sandbox_id_str)
        snapshot_id = str(uuid4())

        session_path = f"/workspace/sessions/{session_id_str}"
        s3_path = (
            f"s3://{self._s3_bucket}/{tenant_id}/snapshots/"
            f"{session_id_str}/{snapshot_id}.tar.gz"
        )

        # Exec into pod to create and upload snapshot (session outputs only)
        exec_command = [
            "/bin/sh",
            "-c",
            f'tar -czf - -C {session_path} outputs | aws s3 cp - {s3_path} --tagging "Type=snapshot"',
        ]

        try:
            # Use exec to run snapshot command in sandbox container
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            logger.debug(f"Snapshot exec output: {resp}")

        except ApiException as e:
            raise RuntimeError(f"Failed to create snapshot: {e}") from e

        # Estimate size (we can't easily get exact size from streamed tar)
        # In production, you might want to query S3 for the actual size
        size_bytes = 0

        storage_path = (
            f"sandbox-snapshots/{tenant_id}/{session_id_str}/{snapshot_id}.tar.gz"
        )

        logger.info(f"Created snapshot for session {session_id}")

        return SnapshotResult(
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        """Check if a session's workspace directory exists in the pod.

        Execs into pod to check for /workspace/sessions/{session_id}/outputs/.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to check

        Returns:
            True if the session workspace exists, False otherwise
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}/outputs"

        # Use exec to check if directory exists
        exec_command = [
            "/bin/sh",
            "-c",
            f'[ -d "{session_path}" ] && echo "EXISTS" || echo "NOT_EXISTS"',
        ]

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            return "EXISTS" in resp

        except ApiException as e:
            logger.warning(
                f"Failed to check session workspace exists for {session_id}: {e}"
            )
            return False

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int,
    ) -> None:
        """Download snapshot from S3, extract into session workspace, and start NextJS.

        Since the sandbox pod doesn't have S3 access, this method:
        1. Downloads snapshot from S3 (using boto3 directly)
        2. Creates the session directory structure in pod
        3. Streams the tar.gz into the pod via kubectl exec
        4. Starts the NextJS dev server

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in S3 (relative path)
            tenant_id: Tenant identifier for storage access
            nextjs_port: Port number for the NextJS dev server

        Raises:
            RuntimeError: If snapshot restoration fails
            FileNotFoundError: If snapshot does not exist
        """
        import tempfile

        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        # Build full S3 path
        s3_key = snapshot_storage_path

        logger.info(f"Restoring snapshot for session {session_id} from {s3_key}")

        # Download snapshot from S3 - uses IAM roles (IRSA)
        s3_client = build_s3_client()
        tmp_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name

            try:
                s3_client.download_file(self._s3_bucket, s3_key, tmp_path)
            except s3_client.exceptions.NoSuchKey:
                raise FileNotFoundError(
                    f"Snapshot not found: s3://{self._s3_bucket}/{s3_key}"
                )

            # Create session directory structure in pod
            # Use shlex.quote to prevent shell injection
            safe_session_path = shlex.quote(session_path)
            setup_script = f"""
set -e
mkdir -p {safe_session_path}/outputs
"""
            k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", setup_script],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            # Stream tar.gz into pod and extract
            # We use kubectl exec with stdin to pipe the tar file
            with open(tmp_path, "rb") as tar_file:
                tar_data = tar_file.read()

            # Use base64 encoding to safely transfer binary data
            import base64

            tar_b64 = base64.b64encode(tar_data).decode("ascii")

            # Extract in the session directory (tar was created with outputs/ as root)
            extract_script = f"""
set -e
cd {safe_session_path}
echo '{tar_b64}' | base64 -d | tar -xzf -
"""
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", extract_script],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            logger.debug(f"Snapshot restore output: {resp}")
            logger.info(f"Restored snapshot for session {session_id}")

            # Start NextJS dev server (check node_modules since restoring from snapshot)
            start_script = _build_nextjs_start_script(
                safe_session_path, nextjs_port, check_node_modules=True
            )
            k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", start_script],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(
                f"Started NextJS server for session {session_id} on port {nextjs_port}"
            )

        except ApiException as e:
            raise RuntimeError(f"Failed to restore snapshot: {e}") from e
        finally:
            # Cleanup temp file
            if tmp_path:
                try:
                    import os

                    os.unlink(tmp_path)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup temp file {tmp_path}: {cleanup_error}"
                    )

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check if the sandbox pod is healthy (can exec into it).

        Args:
            sandbox_id: The sandbox ID to check
            timeout: Health check timeout in seconds

        Returns:
            True if sandbox is healthy, False otherwise
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        exec_client = ACPExecClient(
            pod_name=pod_name,
            namespace=self._namespace,
            container="sandbox",
        )
        return exec_client.health_check(timeout=timeout)

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream ACP events.

        Runs `opencode acp` via kubectl exec in the sandbox pod.
        The agent runs in the session-specific workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID (determines workspace directory)
            message: The message content to send

        Yields:
            Typed ACP schema event objects
        """
        packet_logger = get_packet_logger()
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        # Log ACP client creation
        packet_logger.log_acp_client_start(
            sandbox_id, session_id, session_path, context="k8s"
        )

        exec_client = ACPExecClient(
            pod_name=pod_name,
            namespace=self._namespace,
            container="sandbox",
        )

        # Log the send_message call at sandbox manager level
        packet_logger.log_session_start(session_id, sandbox_id, message)

        events_count = 0
        try:
            exec_client.start(cwd=session_path)
            for event in exec_client.send_message(message):
                events_count += 1
                yield event

            # Log successful completion
            packet_logger.log_session_end(
                session_id, success=True, events_count=events_count
            )
        except Exception as e:
            # Log failure
            packet_logger.log_session_end(
                session_id, success=False, error=str(e), events_count=events_count
            )
            raise
        finally:
            exec_client.stop()
            # Log client stop
            packet_logger.log_acp_client_stop(sandbox_id, session_id, context="k8s")

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the session's outputs directory.

        For Kubernetes backend, we exec into the pod to list files.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/outputs/

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        # _get_pod_name needs string
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize path by removing '..' components individually
        path_obj = Path(path.lstrip("/"))
        clean_parts = [p for p in path_obj.parts if p != ".."]
        clean_path = str(Path(*clean_parts)) if clean_parts else "."
        target_path = f"/workspace/sessions/{session_id}/{clean_path}"
        # Use shlex.quote to prevent command injection
        quoted_path = shlex.quote(target_path)

        logger.info(f"Listing directory {target_path} in pod {pod_name}")

        # Use exec to list directory
        # -L follows symlinks (important for files/ -> /workspace/demo_data)
        exec_command = [
            "/bin/sh",
            "-c",
            f"ls -laL --time-style=+%s {quoted_path} 2>/dev/null || echo 'ERROR_NOT_FOUND'",
        ]

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            if "ERROR_NOT_FOUND" in resp:
                raise ValueError(f"Path not found or not a directory: {path}")

            entries = self._parse_ls_output(resp, clean_path)
            return sorted(entries, key=lambda e: (not e.is_directory, e.name.lower()))

        except ApiException as e:
            raise RuntimeError(f"Failed to list directory: {e}") from e

    def _parse_ls_output(self, ls_output: str, base_path: str) -> list[FilesystemEntry]:
        """Parse ls -la output into FilesystemEntry objects.

        Handles regular files, directories, and symlinks. Symlinks to directories
        are treated as directories for navigation purposes.
        """
        entries = []
        lines = ls_output.strip().split("\n")

        logger.debug(f"Parsing {len(lines)} lines of ls output for {base_path}")

        for line in lines:
            logger.debug(f"Parsing line: {line}")

            # Skip header line and . / .. entries
            if line.startswith("total") or not line:
                continue

            parts = line.split()
            # ls -la --time-style=+%s format: perms links owner group size timestamp name
            # Minimum 7 parts for a simple filename
            if len(parts) < 7:
                continue

            # Handle symlinks: format is "name -> target"
            # For symlinks, parts[-1] is the target, not the name
            is_symlink = line.startswith("l")
            if is_symlink and " -> " in line:
                # Extract name from the "name -> target" portion
                # Filename starts at index 6 (after perms, links, owner, group, size, timestamp)
                try:
                    # Rejoin from index 6 onwards to handle names with spaces
                    name_and_target = " ".join(parts[6:])
                    if " -> " in name_and_target:
                        name = name_and_target.split(" -> ")[0]
                    else:
                        name = parts[-1]
                except (IndexError, ValueError):
                    name = parts[-1]
            else:
                # For regular files/directories, name is at index 6 or later (with spaces)
                name = " ".join(parts[6:])

            if name in (".", ".."):
                continue

            # Directories start with 'd', symlinks start with 'l'
            # Treat symlinks as directories (they typically point to directories
            # in our sandbox setup, like files/ -> /workspace/demo_data)
            is_directory = line.startswith("d") or is_symlink
            size_str = parts[4]

            try:
                size = int(size_str) if not is_directory else None
            except ValueError:
                size = None

            # Guess MIME type for files based on extension
            mime_type = mimetypes.guess_type(name)[0] if not is_directory else None

            entry_path = f"{base_path}/{name}".lstrip("/")
            entries.append(
                FilesystemEntry(
                    name=name,
                    path=entry_path,
                    is_directory=is_directory,
                    size=size,
                    mime_type=mime_type,
                )
            )

        return entries

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        """Read a file from the session's workspace.

        For Kubernetes backend, we exec into the pod to read the file.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        # _get_pod_name needs string
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize path by removing '..' components individually
        path_obj = Path(path.lstrip("/"))
        clean_parts = [p for p in path_obj.parts if p != ".."]
        clean_path = str(Path(*clean_parts)) if clean_parts else "."
        target_path = f"/workspace/sessions/{session_id}/{clean_path}"
        # Use shlex.quote to prevent command injection
        quoted_path = shlex.quote(target_path)

        # Use exec to read file with base64 encoding to handle binary data
        # Base64 encode the output to safely transport binary content
        exec_command = [
            "/bin/sh",
            "-c",
            f"if [ -f {quoted_path} ]; then base64 {quoted_path}; else echo 'ERROR_NOT_FOUND'; fi",
        ]

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            if "ERROR_NOT_FOUND" in resp:
                raise ValueError(f"File not found: {path}")

            # Decode base64 content
            try:
                content = base64.b64decode(resp.strip())
            except binascii.Error as e:
                logger.error(f"Failed to decode base64 content: {e}")
                raise RuntimeError(f"Failed to decode file content: {e}") from e

            return content

        except ApiException as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Get the webapp URL for a session's Next.js server.

        For Kubernetes backend, returns internal cluster service URL.

        Args:
            sandbox_id: The sandbox ID
            port: The session's allocated Next.js port

        Returns:
            Internal cluster URL for the Next.js server on the specified port
        """
        return self._get_nextjs_url(str(sandbox_id), port)

    def sync_files(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
    ) -> bool:
        """Sync files from S3 to the running pod via the file-sync sidecar.

        Executes `aws s3 sync` in the file-sync sidecar container to download
        any new or changed files from S3 to /workspace/files/.

        This is safe to call multiple times - aws s3 sync is idempotent.

        Args:
            sandbox_id: The sandbox UUID
            user_id: The user ID (for S3 path construction)
            tenant_id: The tenant ID (for S3 path construction)

        Returns:
            True if sync was successful, False otherwise.
        """
        pod_name = self._get_pod_name(str(sandbox_id))

        sync_command = [
            "/bin/sh",
            "-c",
            f'aws s3 sync "s3://{self._s3_bucket}/{tenant_id}/knowledge/{str(user_id)}/" /workspace/files/',
        ]
        resp = k8s_stream(
            self._stream_core_api.connect_get_namespaced_pod_exec,
            pod_name,
            self._namespace,
            container="file-sync",  # Execute in sidecar, not sandbox container
            command=sync_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        logger.debug(f"File sync response: {resp}")
        return True

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload a file to the session's attachments directory.

        Uses tar streaming via stdin for efficient binary transfer.
        Handles filename collisions atomically within the shell script.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            filename: Sanitized filename
            content: File content as bytes

        Returns:
            Relative path where file was saved (e.g., "attachments/doc.pdf")

        Raises:
            RuntimeError: If upload fails
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        target_dir = f"/workspace/sessions/{session_id}/attachments"

        # Create tar archive in memory
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(content)
            tar.addfile(tarinfo, io.BytesIO(content))
        tar_data = tar_buffer.getvalue()

        # Shell script that:
        # 1. Creates target directory and temp extraction directory
        # 2. Extracts tar to temp directory
        # 3. Moves file to target with collision handling
        # 4. Cleans up temp directory
        # 5. Outputs final filename
        script = f"""
set -e
target_dir="{target_dir}"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$target_dir"
tar xf - -C "$tmpdir"

# Find the extracted file (first file in tmpdir)
original=$(ls -1 "$tmpdir" | head -1)
base="$original"

cd "$target_dir"
if [ -f "$base" ]; then
    stem="${{base%.*}}"
    ext="${{base##*.}}"
    [ "$stem" = "$base" ] && ext="" || ext=".$ext"
    i=1
    while [ -f "${{stem}}_${{i}}${{ext}}" ]; do i=$((i+1)); done
    base="${{stem}}_${{i}}${{ext}}"
fi

mv "$tmpdir/$original" "$target_dir/$base"
chmod 644 "$target_dir/$base"
echo "$base"
"""

        try:
            # Open WebSocket connection with stdin enabled
            ws_client = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", script],
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,  # Return WSClient instead of string
            )

            # Write tar data to stdin
            ws_client.write_stdin(tar_data)
            ws_client.close()

            # Read response
            stdout_data = ""
            stderr_data = ""
            while ws_client.is_open():
                ws_client.update(timeout=30)
                if ws_client.peek_stdout():
                    stdout_data += ws_client.read_stdout()
                if ws_client.peek_stderr():
                    stderr_data += ws_client.read_stderr()

            # Get any remaining data
            stdout_data += ws_client.read_stdout() or ""
            stderr_data += ws_client.read_stderr() or ""

            if stderr_data.strip():
                logger.warning(f"Upload stderr: {stderr_data.strip()}")

            # Last line of output is the final filename
            final_filename = stdout_data.strip().split("\n")[-1]

            if not final_filename:
                raise RuntimeError(
                    f"Upload failed - no filename returned. stderr: {stderr_data}"
                )

            logger.info(
                f"Uploaded file to session {session_id}: attachments/{final_filename} "
                f"({len(content)} bytes via tar)"
            )

            return f"attachments/{final_filename}"

        except ApiException as e:
            raise RuntimeError(f"Failed to upload file: {e}") from e

    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's workspace.

        Uses kubectl exec to delete the file from the pod.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path to the file (e.g., "attachments/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If path traversal attempted or invalid characters
        """
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: robust path sanitization
        # Reject paths with traversal patterns, URL-encoded characters, or null bytes
        if re.search(r"\.\.", path) or "%" in path or "\x00" in path:
            raise ValueError("Invalid path: potential path traversal detected")

        # Reject paths with shell metacharacters that could be exploited
        if re.search(r'[;&|`$(){}[\]<>\'"\n\r\\]', path):
            raise ValueError("Invalid path: contains disallowed characters")

        clean_path = path.lstrip("/")

        # Verify path only contains safe characters (alphanumeric, dash, underscore, dot, forward slash)
        if not re.match(r"^[a-zA-Z0-9_\-./]+$", clean_path):
            raise ValueError("Invalid path: contains disallowed characters")

        target_path = f"/workspace/sessions/{session_id}/{clean_path}"

        # Use exec to delete file
        exec_command = [
            "/bin/sh",
            "-c",
            f'[ -f "{target_path}" ] && rm "{target_path}" && echo "DELETED" || echo "NOT_FOUND"',
        ]

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
            )

            deleted = "DELETED" in resp
            if deleted:
                logger.info(f"Deleted file from session {session_id}: {path}")
            else:
                logger.debug(
                    f"File not found for deletion in session {session_id}: {path}"
                )

            return deleted

        except ApiException as e:
            raise RuntimeError(f"Failed to delete file: {e}") from e

    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        """Get current file count and total size for a session's attachments.

        Uses kubectl exec to query the pod's attachments directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID

        Returns:
            Tuple of (file_count, total_size_bytes)
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        target_dir = f"/workspace/sessions/{session_id}/attachments"

        # Get file count and total size in one command
        # Uses find to list files, wc -l for count, and du for size
        exec_command = [
            "/bin/sh",
            "-c",
            f"""
if [ -d "{target_dir}" ]; then
    count=$(find "{target_dir}" -maxdepth 1 -type f 2>/dev/null | wc -l)
    size=$(du -sb "{target_dir}" 2>/dev/null | cut -f1)
    echo "$count $size"
else
    echo "0 0"
fi
""",
        ]

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
            )

            # Parse response: "count size"
            parts = resp.strip().split()
            if len(parts) >= 2:
                try:
                    file_count = int(parts[0])
                    # du includes directory overhead, but for limits this is fine
                    total_size = int(parts[1])
                    return file_count, total_size
                except ValueError:
                    logger.warning(f"Failed to parse upload stats: {resp}")
                    return 0, 0

            return 0, 0

        except ApiException as e:
            logger.warning(f"Failed to get upload stats: {e}")
            return 0, 0
