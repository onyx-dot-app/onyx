"""Kubernetes-based sandbox manager for production deployments.

KubernetesSandboxManager provisions sandboxes as Kubernetes pods with true
container isolation. Each sandbox runs in its own pod with dedicated resources.

Key features:
- Pod-based isolation (not process-level)
- S3-based snapshots via init containers
- Cluster-native service discovery
- RBAC-controlled resource management

Use get_sandbox_manager() from base.py to get the appropriate implementation.
"""

import json
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
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.llm import fetch_default_provider
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_FILE_SYNC_SERVICE_ACCOUNT
from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SANDBOX_SERVICE_ACCOUNT_NAME
from onyx.server.features.build.db.sandbox import (
    create_sandbox__no_commit as db_create_sandbox__no_commit,
)
from onyx.server.features.build.db.sandbox import create_snapshot as db_create_snapshot
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.kubernetes.internal.acp_http_client import (
    ACPEvent,
)
from onyx.server.features.build.sandbox.kubernetes.internal.acp_http_client import (
    ACPHttpClient,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotInfo
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Constants for pod configuration
NEXTJS_PORT = 3000
AGENT_PORT = 8081
POD_READY_TIMEOUT_SECONDS = 120
POD_READY_POLL_INTERVAL_SECONDS = 2


class KubernetesSandboxManager(SandboxManager):
    """Kubernetes-based sandbox manager for production deployments.

    Manages sandboxes as Kubernetes pods with:
    - Init containers for S3 file sync (snapshots, knowledge files, uploads)
    - Main sandbox container running Next.js + opencode agent
    - ClusterIP services for network access

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

        # Track ACP HTTP clients in memory
        self._acp_clients: dict[str, ACPHttpClient] = {}

        # Load AGENTS.md template path
        build_dir = Path(__file__).parent.parent.parent  # /onyx/server/features/build/
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"

        logger.info(
            f"KubernetesSandboxManager initialized: "
            f"namespace={self._namespace}, image={self._image}"
        )

    def _get_pod_name(self, session_id: str) -> str:
        """Generate pod name from session ID."""
        return f"sandbox-{str(session_id)[:8]}"

    def _get_service_name(self, session_id: str) -> str:
        """Generate service name from session ID."""
        return self._get_pod_name(session_id)

    def _get_agent_url(self, session_id: str) -> str:
        """Get the internal cluster URL for the agent HTTP server."""
        service_name = self._get_service_name(session_id)
        return f"http://{service_name}.{self._namespace}.svc.cluster.local:{AGENT_PORT}"

    def _get_nextjs_url(self, session_id: str) -> str:
        """Get the internal cluster URL for the Next.js server."""
        service_name = self._get_service_name(session_id)
        return (
            f"http://{service_name}.{self._namespace}.svc.cluster.local:{NEXTJS_PORT}"
        )

    def _load_agent_instructions(self) -> str:
        """Load agent instructions from template file."""
        if self._agent_instructions_template_path.exists():
            return self._agent_instructions_template_path.read_text()
        return "# Agent Instructions\n\nNo custom instructions provided."

    def _create_sandbox_pod(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        llm_provider: str,
        llm_model: str,
        llm_api_key: str,
        llm_api_base: str | None,
        snapshot_id: str | None = None,
    ) -> client.V1Pod:
        """Create Pod specification for sandbox."""
        pod_name = self._get_pod_name(session_id)

        # Load agent instructions
        agent_instructions = self._load_agent_instructions()

        # Environment variables for init container
        init_env = [
            client.V1EnvVar(name="SESSION_ID", value=session_id),
            client.V1EnvVar(name="TENANT_ID", value=tenant_id),
            client.V1EnvVar(name="USER_ID", value=user_id),
            client.V1EnvVar(name="S3_BUCKET", value=self._s3_bucket),
            client.V1EnvVar(name="AGENT_INSTRUCTIONS", value=agent_instructions),
        ]
        if snapshot_id:
            init_env.append(client.V1EnvVar(name="SNAPSHOT_ID", value=snapshot_id))

        # Init container for S3 file sync
        init_container = client.V1Container(
            name="file-sync",
            image="amazon/aws-cli:latest",
            env=init_env,
            command=["/bin/sh", "-c"],
            args=[
                """
set -e

# Write agent instructions to file
echo "Writing agent instructions"
printf '%s' "$AGENT_INSTRUCTIONS" > /workspace/AGENTS.md

# Restore from snapshot if provided
if [ -n "$SNAPSHOT_ID" ]; then
    echo "Restoring from snapshot: $SNAPSHOT_ID"
    aws s3 cp "s3://$S3_BUCKET/$TENANT_ID/snapshots/$SESSION_ID/$SNAPSHOT_ID.tar.gz" /tmp/snapshot.tar.gz
    tar -xzf /tmp/snapshot.tar.gz -C /workspace/outputs
    rm /tmp/snapshot.tar.gz
fi

# Sync knowledge files for this user/tenant
echo "Syncing knowledge files for tenant: $TENANT_ID / user: $USER_ID"
aws s3 sync "s3://$S3_BUCKET/$TENANT_ID/knowledge/$USER_ID/" /workspace/files/ --quiet || true

# Sync user-uploaded files for this session
echo "Syncing user uploads for session: $SESSION_ID"
aws s3 sync "s3://$S3_BUCKET/$TENANT_ID/uploads/$SESSION_ID/" /workspace/user_uploaded_files/ --quiet || true

echo "File sync complete"
"""
            ],
            volume_mounts=[
                client.V1VolumeMount(name="workspace", mount_path="/workspace"),
                client.V1VolumeMount(name="outputs", mount_path="/workspace/outputs"),
                client.V1VolumeMount(name="files", mount_path="/workspace/files"),
                client.V1VolumeMount(
                    name="user-uploads", mount_path="/workspace/user_uploaded_files"
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": "1000m", "memory": "1Gi"},
            ),
        )

        # Build opencode config JSON
        opencode_config: dict[str, str | list[str]] = {
            "provider": llm_provider,
            "model": llm_model,
            "apiKey": llm_api_key,
        }
        if llm_api_base:
            opencode_config["apiBase"] = llm_api_base
        if OPENCODE_DISABLED_TOOLS:
            opencode_config["disabledTools"] = OPENCODE_DISABLED_TOOLS

        # Main sandbox container
        sandbox_env = [
            client.V1EnvVar(name="SESSION_ID", value=session_id),
            client.V1EnvVar(name="OPENCODE_CONFIG", value=json.dumps(opencode_config)),
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
                client.V1VolumeMount(
                    name="user-uploads",
                    mount_path="/workspace/user_uploaded_files",
                    read_only=True,
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
            #     http_get=client.V1HTTPGetAction(path="/health", port=AGENT_PORT),
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
            client.V1Volume(
                name="user-uploads",
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
                    "onyx.app/session-id": session_id,
                    "onyx.app/tenant-id": tenant_id,
                },
            ),
            spec=pod_spec,
        )

    def _create_sandbox_service(
        self,
        session_id: str,
        tenant_id: str,
    ) -> client.V1Service:
        """Create ClusterIP Service for sandbox pod."""
        service_name = self._get_service_name(session_id)

        return client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "sandbox",
                    "app.kubernetes.io/managed-by": "onyx",
                    "onyx.app/session-id": session_id,
                    "onyx.app/tenant-id": tenant_id,
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"onyx.app/session-id": session_id},
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

                phase = pod.status.phase

                # Check for failure conditions
                if phase == "Failed":
                    raise RuntimeError(f"Pod {pod_name} failed to start")

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

        logger.warning(f"Timeout waiting for pod {pod_name} to become ready")
        return False

    def provision(
        self,
        session_id: str,
        tenant_id: str,
        file_system_path: str,
        db_session: Session,
        snapshot_id: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox as a Kubernetes pod.

        1. Check concurrent sandbox limit for tenant
        2. Create Pod (init container handles S3 file sync)
        3. Create Service for pod
        4. Wait for pod to be ready
        5. Store sandbox record in DB
        """
        logger.info(
            f"Starting Kubernetes sandbox provisioning for session {session_id}, "
            f"tenant {tenant_id}"
        )

        session_uuid = UUID(session_id)
        pod_name = self._get_pod_name(session_id)

        # Check limit (only enforce on cloud deployments)
        if MULTI_TENANT:
            running_count = get_running_sandbox_count_by_tenant(db_session, tenant_id)
            if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
                raise ValueError(
                    f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) "
                    f"reached for tenant"
                )

        # Fetch LLM provider configuration
        llm_provider = fetch_default_provider(db_session)
        if not llm_provider:
            raise RuntimeError(
                "No default LLM provider configured. "
                "Please configure an LLM provider in admin settings."
            )

        # Get user ID from current context (simplified - you may need to pass this in)
        user_id = str(uuid4())  # Placeholder - should come from session

        try:
            # 1. Create Pod
            logger.debug(f"Creating Pod {pod_name}")
            pod = self._create_sandbox_pod(
                session_id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                llm_provider=llm_provider.provider,
                llm_model=llm_provider.default_model_name,
                llm_api_key=llm_provider.api_key or "",
                llm_api_base=llm_provider.api_base,
                snapshot_id=snapshot_id,
            )
            self._core_api.create_namespaced_pod(
                namespace=self._namespace,
                body=pod,
            )

            # 2. Create Service
            logger.debug(f"Creating Service {self._get_service_name(session_id)}")
            service = self._create_sandbox_service(session_id, tenant_id)
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

            # 4. Create DB record
            logger.debug("Creating sandbox database record")
            sandbox = db_create_sandbox__no_commit(
                db_session=db_session,
                session_id=session_uuid,
                nextjs_port=NEXTJS_PORT,  # Always 3000 within cluster
            )

            update_sandbox_status__no_commit(
                db_session, sandbox.id, SandboxStatus.RUNNING
            )
            db_session.commit()

            logger.info(
                f"Provisioned Kubernetes sandbox {sandbox.id} for session {session_id}, "
                f"pod: {pod_name}"
            )

            return SandboxInfo(
                id=str(sandbox.id),
                session_id=session_id,
                directory_path=f"k8s://{self._namespace}/{pod_name}",
                status=SandboxStatus.RUNNING,
                created_at=sandbox.created_at,
                last_heartbeat=None,
            )

        except Exception as e:
            # Cleanup on failure
            logger.error(
                f"Kubernetes sandbox provisioning failed for session {session_id}: {e}",
                exc_info=True,
            )
            self._cleanup_kubernetes_resources(session_id)
            raise

    def _cleanup_kubernetes_resources(self, session_id: str) -> None:
        """Clean up Kubernetes resources for a session."""
        pod_name = self._get_pod_name(session_id)
        service_name = self._get_service_name(session_id)

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

    def terminate(self, sandbox_id: str, db_session: Session) -> None:
        """Terminate a sandbox and clean up Kubernetes resources.

        1. Close ACP HTTP client
        2. Delete Service, Pod
        3. Update DB status
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            logger.warning(f"Sandbox {sandbox_id} not found for termination")
            return

        session_id = str(sandbox.session_id)

        # Close ACP HTTP client
        client = self._acp_clients.pop(sandbox_id, None)
        if client:
            try:
                client.close()
            except Exception as e:
                logger.warning(
                    f"Error closing ACP client for sandbox {sandbox_id}: {e}"
                )

        # Clean up Kubernetes resources
        self._cleanup_kubernetes_resources(session_id)

        # Update status
        update_sandbox_status__no_commit(
            db_session, UUID(sandbox_id), SandboxStatus.TERMINATED
        )
        db_session.commit()

        logger.info(f"Terminated Kubernetes sandbox {sandbox_id}")

    def create_snapshot(
        self, sandbox_id: str, db_session: Session
    ) -> SnapshotInfo | None:
        """Create a snapshot by running a Job that tars outputs and streams to S3.

        For Kubernetes backend, we exec into the pod to create the snapshot.
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        session_id = str(sandbox.session_id)
        pod_name = self._get_pod_name(session_id)
        tenant_id = get_current_tenant_id()
        snapshot_id = str(uuid4())

        s3_path = (
            f"s3://{self._s3_bucket}/{tenant_id}/snapshots/"
            f"{session_id}/{snapshot_id}.tar.gz"
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

        # Create DB record
        storage_path = (
            f"sandbox-snapshots/{tenant_id}/{session_id}/{snapshot_id}.tar.gz"
        )
        snapshot = db_create_snapshot(
            db_session=db_session,
            session_id=sandbox.session_id,
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

        logger.info(f"Created snapshot {snapshot.id} for sandbox {sandbox_id}")

        return SnapshotInfo(
            id=str(snapshot.id),
            session_id=session_id,
            storage_path=storage_path,
            created_at=snapshot.created_at,
            size_bytes=size_bytes,
        )

    def health_check(self, sandbox_id: str, db_session: Session) -> bool:
        """Check if the sandbox pod and agent are healthy."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return False

        session_id = str(sandbox.session_id)

        # Get or create ACP HTTP client
        acp_client = self._acp_clients.get(sandbox_id)
        if acp_client is None:
            agent_url = self._get_agent_url(session_id)
            acp_client = ACPHttpClient(agent_url)
            self._acp_clients[sandbox_id] = acp_client

        # Check agent health
        if acp_client.health_check(timeout=5.0):
            update_sandbox_heartbeat(db_session, UUID(sandbox_id))
            return True

        return False

    def send_message(
        self,
        sandbox_id: str,
        message: str,
        db_session: Session,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent via HTTP and stream ACP events."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        session_id = str(sandbox.session_id)

        # Get or create ACP HTTP client
        acp_client = self._acp_clients.get(sandbox_id)
        if acp_client is None or not acp_client.is_initialized:
            agent_url = self._get_agent_url(session_id)
            acp_client = ACPHttpClient(agent_url)
            acp_client.initialize(cwd="/workspace")
            self._acp_clients[sandbox_id] = acp_client

        # Update heartbeat on message send
        update_sandbox_heartbeat(db_session, UUID(sandbox_id))

        for event in acp_client.send_message(message):
            yield event
            # Update heartbeat on activity
            update_sandbox_heartbeat(db_session, UUID(sandbox_id))

    def list_directory(
        self, sandbox_id: str, path: str, db_session: Session
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory.

        For Kubernetes backend, we exec into the pod to list files.
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        session_id = str(sandbox.session_id)
        pod_name = self._get_pod_name(session_id)

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

    def read_file(self, sandbox_id: str, path: str, db_session: Session) -> bytes:
        """Read a file from the sandbox's outputs directory.

        For Kubernetes backend, we exec into the pod to read the file.
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        session_id = str(sandbox.session_id)
        pod_name = self._get_pod_name(session_id)

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

    def get_sandbox_info(
        self, sandbox_id: str, db_session: Session
    ) -> SandboxInfo | None:
        """Get information about a sandbox."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return None

        session_id = str(sandbox.session_id)
        pod_name = self._get_pod_name(session_id)

        return SandboxInfo(
            id=str(sandbox.id),
            session_id=session_id,
            directory_path=f"k8s://{self._namespace}/{pod_name}",
            status=sandbox.status,
            created_at=sandbox.created_at,
            last_heartbeat=sandbox.last_heartbeat,
        )

    def cancel_agent(self, sandbox_id: str) -> None:
        """Cancel the current agent operation."""
        acp_client = self._acp_clients.get(sandbox_id)
        if acp_client:
            acp_client.cancel()

    def get_nextjs_url(self, sandbox_id: str, db_session: Session) -> str:
        """Get the Next.js URL for the sandbox.

        Used for proxying preview requests to the sandbox.
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        session_id = str(sandbox.session_id)
        return self._get_nextjs_url(session_id)
