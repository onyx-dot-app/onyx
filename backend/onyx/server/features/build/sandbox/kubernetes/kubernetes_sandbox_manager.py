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

import json
import os
import threading
import time
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from kubernetes import client  # type: ignore
from kubernetes import config
from kubernetes.client.rest import ApiException  # type: ignore
from kubernetes.stream import stream as k8s_stream  # type: ignore

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_FILE_SYNC_SERVICE_ACCOUNT
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SANDBOX_SERVICE_ACCOUNT_NAME
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
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constants for pod configuration
NEXTJS_PORT = 3000
AGENT_PORT = 8081
POD_READY_TIMEOUT_SECONDS = 120
POD_READY_POLL_INTERVAL_SECONDS = 2


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

        self._core_api = client.CoreV1Api()
        self._batch_api = client.BatchV1Api()
        self._networking_api = client.NetworkingV1Api()

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

    def _get_nextjs_url(self, sandbox_id: str) -> str:
        """Get the internal cluster URL for the Next.js server."""
        service_name = self._get_service_name(sandbox_id)
        return (
            f"http://{service_name}.{self._namespace}.svc.cluster.local:{NEXTJS_PORT}"
        )

    def _load_agent_instructions(
        self,
        provider: str | None = None,
        model_name: str | None = None,
        nextjs_port: int | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> str:
        """Load and populate agent instructions from template file.

        Args:
            provider: LLM provider type
            model_name: Model name
            nextjs_port: Next.js port
            disabled_tools: List of disabled tools
            user_name: User's name for personalization
            user_role: User's role/title for personalization

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
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port if nextjs_port else NEXTJS_PORT,
            disabled_tools=disabled_tools,
            user_name=user_name,
            user_role=user_role,
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

        # Init container for S3 file sync (knowledge files only)
        # Outputs template is baked into the main container image at /workspace/templates/outputs/
        init_container = client.V1Container(
            name="file-sync",
            image="amazon/aws-cli:latest",
            env=_get_local_aws_credential_env_vars(),
            command=["/bin/sh", "-c"],
            args=[
                f"""
set -e

# Sync knowledge files for this user/tenant (shared across sessions)
echo "Syncing knowledge files for tenant: {tenant_id} / user: {user_id}"
aws s3 sync "s3://{self._s3_bucket}/{tenant_id}/knowledge/{user_id}/" /workspace/files/

echo "Sandbox init complete (user-level only, no sessions yet)"
"""
            ],
            volume_mounts=[
                client.V1VolumeMount(name="files", mount_path="/workspace/files"),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": "1000m", "memory": "1Gi"},
            ),
        )

        # Main sandbox container
        sandbox_container = client.V1Container(
            name="sandbox",
            image=self._image,
            image_pull_policy="IfNotPresent",
            ports=[
                client.V1ContainerPort(name="nextjs", container_port=NEXTJS_PORT),
                client.V1ContainerPort(name="agent", container_port=AGENT_PORT),
            ],
            volume_mounts=[
                client.V1VolumeMount(
                    name="files", mount_path="/workspace/files", read_only=True
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "500m", "memory": "1Gi"},
                limits={"cpu": "2000m", "memory": "4Gi"},
            ),
            # TODO: Re-enable probes when sandbox container runs actual services
            # readiness_probe=client.V1Probe(
            #     http_get=client.V1HTTPGetAction(path="/", port=NEXTJS_PORT),
            #     initial_delay_seconds=10,
            #     period_seconds=5,
            #     timeout_seconds=3,
            #     failure_threshold=6,
            # ),
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
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="10Gi"),
            ),
            client.V1Volume(
                name="files",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="1Gi"),
            ),
        ]

        # Pod spec
        pod_spec = client.V1PodSpec(
            service_account_name=self._file_sync_service_account,
            init_containers=[init_container],
            containers=[sandbox_container],
            volumes=volumes,
            restart_policy="Never",
            termination_grace_period_seconds=30,
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
        """Create ClusterIP Service for sandbox pod."""
        # Convert UUID objects to strings if needed (Kubernetes client requires strings)
        sandbox_id_str: str = str(sandbox_id)
        tenant_id_str: str = str(tenant_id)

        service_name = self._get_service_name(sandbox_id_str)

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
                ports=[
                    client.V1ServicePort(
                        name="nextjs", port=NEXTJS_PORT, target_port=NEXTJS_PORT
                    ),
                    client.V1ServicePort(
                        name="agent", port=AGENT_PORT, target_port=AGENT_PORT
                    ),
                ],
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

    def _cleanup_kubernetes_resources(self, sandbox_id: str) -> None:
        """Clean up Kubernetes resources for a sandbox."""
        # Convert UUID objects to strings if needed (Kubernetes client requires strings)
        sandbox_id = str(sandbox_id)

        pod_name = self._get_pod_name(sandbox_id)
        service_name = self._get_service_name(sandbox_id)

        # Delete in reverse order of creation
        try:
            self._core_api.delete_namespaced_service(
                name=service_name,
                namespace=self._namespace,
            )
            logger.debug(f"Deleted Service {service_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error deleting Service {service_name}: {e}")

        try:
            self._core_api.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            logger.debug(f"Deleted Pod {pod_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error deleting Pod {pod_name}: {e}")

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
    ) -> None:
        """Set up a session workspace within an existing sandbox pod.

        Executes kubectl exec to:
        1. Create sessions/$session_id/ directory
        2. Copy outputs template from local templates (downloaded during init)
        3. Write AGENTS.md
        4. Write opencode.json with LLM config

        Note: Snapshot restoration is not supported in Kubernetes mode since the
        main container doesn't have S3 access. Snapshots would need to be
        pre-downloaded during pod provisioning if needed.

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            file_system_path: Not used in k8s (files synced from S3 during init)
            snapshot_path: Optional S3 path - logged but ignored (no S3 access)

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
            nextjs_port=NEXTJS_PORT,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
            user_role=user_role,
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

        setup_script = f"""
set -e

# Create session directory structure
echo "Creating session directory: {session_path}"
mkdir -p {session_path}/outputs
mkdir -p {session_path}/user_uploaded_files

# Setup outputs
{outputs_setup}

# Write agent instructions
echo "Writing AGENTS.md"
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md

# Write opencode config
echo "Writing opencode.json"
printf '%s' '{opencode_json_escaped}' > {session_path}/opencode.json

# Start Next.js dev server in background
echo "Starting Next.js dev server on port {NEXTJS_PORT}..."
cd {session_path}/outputs/web

# Start npm run dev in background with output to log file
nohup npm run dev -- -p {NEXTJS_PORT} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"

# Store PID for potential cleanup
echo $NEXTJS_PID > {session_path}/nextjs.pid

echo "Session workspace setup complete"
"""

        logger.info(
            f"Setting up session workspace {session_id} in sandbox {sandbox_id}"
        )

        try:
            # Execute setup script in the pod
            exec_response = k8s_stream(
                self._core_api.connect_get_namespaced_pod_exec,
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
    ) -> None:
        """Clean up a session workspace (on session delete).

        Executes kubectl exec to remove the session directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
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
                self._core_api.connect_get_namespaced_pod_exec,
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
                self._core_api.connect_get_namespaced_pod_exec,
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

    def health_check(
        self, sandbox_id: UUID, nextjs_port: int | None, timeout: float = 60.0
    ) -> bool:
        """Check if the sandbox pod is healthy (can exec into it).

        Args:
            sandbox_id: The sandbox ID to check
            nextjs_port: Not used in kubernetes
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
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"
        exec_client = ACPExecClient(
            pod_name=pod_name,
            namespace=self._namespace,
            container="sandbox",
        )
        try:
            exec_client.start(cwd=session_path)
            for event in exec_client.send_message(message):
                yield event
        finally:
            exec_client.stop()

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

        # Security: sanitize path
        clean_path = path.lstrip("/").replace("..", "")
        target_path = f"/workspace/sessions/{session_id}/{clean_path}"

        # Use exec to list directory
        exec_command = [
            "/bin/sh",
            "-c",
            f'ls -la --time-style=+%s "{target_path}" 2>/dev/null || echo "ERROR_NOT_FOUND"',
        ]

        try:
            resp = k8s_stream(
                self._core_api.connect_get_namespaced_pod_exec,
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
        """Parse ls -la output into FilesystemEntry objects."""
        entries = []
        lines = ls_output.strip().split("\n")

        for line in lines:
            # Skip header line and . / .. entries
            if line.startswith("total") or not line:
                continue

            parts = line.split()
            if len(parts) < 8:
                continue

            name = parts[-1]
            if name in (".", ".."):
                continue

            is_directory = line.startswith("d")
            size_str = parts[4]
            timestamp_str = parts[5] if len(parts) > 6 else None

            try:
                size_bytes = int(size_str) if not is_directory else None
            except ValueError:
                size_bytes = None

            try:
                modified_at = (
                    datetime.fromtimestamp(int(timestamp_str))
                    if timestamp_str
                    else None
                )
            except (ValueError, TypeError):
                modified_at = None

            entry_path = f"{base_path}/{name}".lstrip("/")
            entries.append(
                FilesystemEntry(
                    name=name,
                    path=entry_path,
                    is_directory=is_directory,
                    size_bytes=size_bytes,
                    modified_at=modified_at,
                )
            )

        return entries

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        """Read a file from the session's outputs directory.

        For Kubernetes backend, we exec into the pod to read the file.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/outputs/

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        # _get_pod_name needs string
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize path
        clean_path = path.lstrip("/").replace("..", "")
        target_path = f"/workspace/sessions/{session_id}/outputs/{clean_path}"

        # Use exec to read file (base64 encode to handle binary)
        exec_command = [
            "/bin/sh",
            "-c",
            f'cat "{target_path}" 2>/dev/null || echo "ERROR_NOT_FOUND"',
        ]

        try:
            resp = k8s_stream(
                self._core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,  # Return raw bytes
            )

            # Read response
            content = b""
            for chunk in resp:
                content += chunk

            if b"ERROR_NOT_FOUND" in content:
                raise ValueError(f"File not found: {path}")

            return content

        except ApiException as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

    def get_nextjs_url(self, sandbox_id: UUID) -> str:
        """Get the Next.js URL for the sandbox.

        Used for proxying preview requests to the sandbox.

        Args:
            sandbox_id: The sandbox ID

        Returns:
            Internal cluster URL for the Next.js server
        """
        return self._get_nextjs_url(str(sandbox_id))
