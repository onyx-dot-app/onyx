"""Kubernetes-based sandbox manager for production deployments.

KubernetesSandboxManager provisions sandboxes as Kubernetes pods with true
container isolation. Each sandbox runs in its own pod with dedicated resources.

Key features:
- Pod-based isolation (not process-level)
- S3-based snapshots via init containers
- Cluster-native service discovery
- RBAC-controlled resource management

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
        tenant_id: str,
        user_id: str,
        llm_provider: str,
        llm_model: str,
        llm_api_key: str,
        llm_api_base: str | None,
        snapshot_id: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> client.V1Pod:
        """Create Pod specification for sandbox."""
        pod_name = self._get_pod_name(sandbox_id)

        # Load agent instructions with dynamic content
        agent_instructions = self._load_agent_instructions(
            provider=llm_provider,
            model_name=llm_model,
            nextjs_port=NEXTJS_PORT,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
            user_role=user_role,
        )

        # Environment variables for init container
        init_env = [
            client.V1EnvVar(name="SANDBOX_ID", value=sandbox_id),
            client.V1EnvVar(name="TENANT_ID", value=tenant_id),
            client.V1EnvVar(name="USER_ID", value=user_id),
            client.V1EnvVar(name="S3_BUCKET", value=self._s3_bucket),
        ]
        if snapshot_id:
            init_env.append(client.V1EnvVar(name="SNAPSHOT_ID", value=snapshot_id))

        # Add local AWS credentials if available (for dev/testing, IRSA handles prod)
        init_env.extend(_get_local_aws_credential_env_vars())

        # Init container for S3 file sync only
        # AGENTS.md is generated by the main container on startup (after files are synced)
        init_container = client.V1Container(
            name="file-sync",
            image="amazon/aws-cli:latest",
            env=init_env,
            command=["/bin/sh", "-c"],
            args=[
                """
set -e

# Restore from snapshot if provided
if [ -n "$SNAPSHOT_ID" ]; then
    echo "Restoring from snapshot: $SNAPSHOT_ID"
    aws s3 cp "s3://$S3_BUCKET/$TENANT_ID/snapshots/$SANDBOX_ID/$SNAPSHOT_ID.tar.gz" /tmp/snapshot.tar.gz
    tar -xzf /tmp/snapshot.tar.gz -C /workspace/outputs
    rm /tmp/snapshot.tar.gz
fi

# Sync knowledge files for this user/tenant
echo "Syncing knowledge files for tenant: $TENANT_ID / user: $USER_ID"
aws s3 sync "s3://$S3_BUCKET/$TENANT_ID/knowledge/$USER_ID/" /workspace/files/

# Copy and unzip output templates for this user/tenant
echo "Copying output template zip for tenant: $TENANT_ID / user: $USER_ID"
aws s3 cp "s3://$S3_BUCKET/craft-output-template/outputs.zip" /tmp/outputs.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/outputs.zip').extractall('/workspace/')"
rm /tmp/outputs.zip

echo "File sync complete"
"""
            ],
            volume_mounts=[
                client.V1VolumeMount(name="workspace", mount_path="/workspace"),
                client.V1VolumeMount(name="outputs", mount_path="/workspace/outputs"),
                client.V1VolumeMount(name="files", mount_path="/workspace/files"),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": "1000m", "memory": "1Gi"},
            ),
        )

        # Build opencode config JSON using shared config builder
        opencode_config = build_opencode_config(
            provider=llm_provider,
            model_name=llm_model,
            api_key=llm_api_key if llm_api_key else None,
            api_base=llm_api_base,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
        )

        # Main sandbox container
        sandbox_env = [
            client.V1EnvVar(name="SANDBOX_ID", value=sandbox_id),
            client.V1EnvVar(name="OPENCODE_CONFIG", value=json.dumps(opencode_config)),
            # Template for AGENTS.md generation (populated by entrypoint script)
            client.V1EnvVar(name="AGENT_INSTRUCTIONS", value=agent_instructions),
        ]

        sandbox_container = client.V1Container(
            name="sandbox",
            image=self._image,
            image_pull_policy="IfNotPresent",
            ports=[
                client.V1ContainerPort(name="nextjs", container_port=NEXTJS_PORT),
                client.V1ContainerPort(name="agent", container_port=AGENT_PORT),
            ],
            env=sandbox_env,
            volume_mounts=[
                client.V1VolumeMount(name="workspace", mount_path="/workspace"),
                client.V1VolumeMount(name="outputs", mount_path="/workspace/outputs"),
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

        # Volumes
        volumes = [
            client.V1Volume(
                name="workspace",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="10Mi"),
            ),
            client.V1Volume(
                name="outputs",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="5Gi"),
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
        file_system_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None = None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox as a Kubernetes pod.

        1. Create Pod (init container handles S3 file sync)
        2. Create Service for pod
        3. Wait for pod to be ready
        4. Return sandbox info

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            file_system_path: Path to the knowledge/source files (not used in k8s)
            llm_config: LLM provider configuration
            nextjs_port: Not used in kubernetes (always 3000 within cluster)
            snapshot_path: Optional snapshot ID to restore from
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md

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
            # 1. Create Pod
            logger.debug(f"Creating Pod {pod_name}")
            pod = self._create_sandbox_pod(
                sandbox_id=str(sandbox_id),
                tenant_id=tenant_id,
                user_id=str(user_id),
                llm_provider=llm_config.provider,
                llm_model=llm_config.model_name,
                llm_api_key=llm_config.api_key or "",
                llm_api_base=llm_config.api_base,
                snapshot_id=snapshot_path,  # snapshot_path is used as snapshot_id
                user_name=user_name,
                user_role=user_role,
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

            logger.info(f"Provisioned Kubernetes sandbox {sandbox_id}, pod: {pod_name}")

            return SandboxInfo(
                sandbox_id=sandbox_id,
                directory_path=f"k8s://{self._namespace}/{pod_name}",
                status=SandboxStatus.RUNNING,
                last_heartbeat=None,
                nextjs_port=NEXTJS_PORT,  # Always 3000 within cluster
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

    def create_snapshot(
        self, sandbox_id: UUID, tenant_id: str
    ) -> SnapshotResult | None:
        """Create a snapshot by running a Job that tars outputs and streams to S3.

        For Kubernetes backend, we exec into the pod to create the snapshot.

        Args:
            sandbox_id: The sandbox ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size

        Raises:
            RuntimeError: If snapshot creation fails
        """
        sandbox_id_str = str(sandbox_id)  # Needed for pod names and S3 paths
        pod_name = self._get_pod_name(sandbox_id_str)
        snapshot_id = str(uuid4())

        s3_path = (
            f"s3://{self._s3_bucket}/{tenant_id}/snapshots/"
            f"{sandbox_id_str}/{snapshot_id}.tar.gz"
        )

        # Exec into pod to create and upload snapshot
        exec_command = [
            "/bin/sh",
            "-c",
            f'tar -czf - -C /workspace outputs | aws s3 cp - {s3_path} --tagging "Type=snapshot"',
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
            f"sandbox-snapshots/{tenant_id}/{sandbox_id_str}/{snapshot_id}.tar.gz"
        )

        logger.info(f"Created snapshot for sandbox {sandbox_id}")

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
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream ACP events.

        Runs `opencode acp` via kubectl exec in the sandbox pod.

        Args:
            sandbox_id: The sandbox ID to send message to
            message: The message content to send

        Yields:
            Typed ACP schema event objects
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        exec_client = ACPExecClient(
            pod_name=pod_name,
            namespace=self._namespace,
            container="sandbox",
        )
        try:
            exec_client.start(cwd="/workspace")
            for event in exec_client.send_message(message):
                yield event
        finally:
            exec_client.stop()

    def list_directory(self, sandbox_id: UUID, path: str) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory.

        For Kubernetes backend, we exec into the pod to list files.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        # _get_pod_name needs string
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize path
        clean_path = path.lstrip("/").replace("..", "")
        target_path = f"/workspace/outputs/{clean_path}"

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

    def read_file(self, sandbox_id: UUID, path: str) -> bytes:
        """Read a file from the sandbox's outputs directory.

        For Kubernetes backend, we exec into the pod to read the file.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        # _get_pod_name needs string
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize path
        clean_path = path.lstrip("/").replace("..", "")
        target_path = f"/workspace/outputs/{clean_path}"

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
