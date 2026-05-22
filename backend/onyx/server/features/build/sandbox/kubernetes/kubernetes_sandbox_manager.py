"""Kubernetes-based sandbox manager for production deployments.

KubernetesSandboxManager provisions sandboxes as Kubernetes pods with true
container isolation. Each sandbox runs in its own pod with dedicated resources.

Key features:
- Pod-based isolation (not process-level)
- S3-based snapshots via the main sandbox container
- Cluster-native service discovery
- RBAC-controlled resource management
- User-shared sandbox model with per-session workspaces

Architecture Note (User-Shared Sandbox Model):
- One pod per user (shared across all user's sessions)
- provision() creates the pod
- setup_session_workspace() creates per-session workspace via kubectl exec
- cleanup_session_workspace() removes session workspace via kubectl exec
- terminate() destroys the entire pod (all sessions)

Directory Structure (inside pod):
    /workspace/
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
import hashlib
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
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import httpx
from acp.schema import PromptResponse
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import PublicFormat
from kubernetes import client
from kubernetes import config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream as k8s_stream

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_API_SERVER_URL
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.features.build.configs import SANDBOX_POD_CPU_LIMIT
from onyx.server.features.build.configs import SANDBOX_POD_CPU_REQUEST
from onyx.server.features.build.configs import SANDBOX_POD_MEMORY_LIMIT
from onyx.server.features.build.configs import SANDBOX_POD_MEMORY_REQUEST
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SANDBOX_SERVICE_ACCOUNT_NAME
from onyx.server.features.build.sandbox.acp.base import ACPEvent
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR
from onyx.server.features.build.sandbox.base import BUN_IMAGE_CACHE_DIR
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.kubernetes.docker.sandbox_daemon.models import (
    SnapshotCreateRequest,
)
from onyx.server.features.build.sandbox.kubernetes.docker.sandbox_daemon.models import (
    SnapshotCreateResponse,
)
from onyx.server.features.build.sandbox.kubernetes.docker.sandbox_daemon.models import (
    SnapshotRestoreRequest,
)
from onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client import (
    ACPExecClient,
)
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import RetriableWriteError
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.util.agent_instructions import (
    ATTACHMENTS_SECTION_CONTENT,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_config,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# API server pod hostname — used to identify which replica is handling a request.
# In K8s, HOSTNAME is set to the pod name (e.g., "api-server-dpgg7").
_API_SERVER_HOSTNAME = os.environ.get("HOSTNAME", "unknown")

# Constants for pod configuration
# Note: Next.js ports are dynamically allocated from SANDBOX_NEXTJS_PORT_START to
# SANDBOX_NEXTJS_PORT_END range, with one port per session.
AGENT_PORT = 8081
PUSH_DAEMON_PORT = 8731
POD_READY_TIMEOUT_SECONDS = 60
# Progressive poll cadence: short intervals up front (pods usually become
# Ready in 12–18s, so we want to catch the transition quickly), then back
# off so a stuck pod doesn't hammer the API server. Each tuple is
# (count, interval_seconds). Sum of count × interval must stay ≤
# POD_READY_TIMEOUT_SECONDS.
POD_READY_POLL_SCHEDULE: tuple[tuple[int, float], ...] = (
    (6, 0.5),  # 0–3s
    (5, 1.0),  # 3–8s
    (26, 2.0),  # 8–60s
)

# Resource deletion timeout and polling interval
# Kubernetes deletes are async - we need to wait for resources to actually be gone
RESOURCE_DELETION_TIMEOUT_SECONDS = 30
RESOURCE_DELETION_POLL_INTERVAL_SECONDS = 0.5


_PUSH_PRIVATE_KEY_ENV = "ONYX_SANDBOX_PUSH_PRIVATE_KEY"
_PUSH_PUBLIC_KEY_ENV = "ONYX_SANDBOX_PUSH_PUBLIC_KEY"

_push_private_key: Ed25519PrivateKey | None = None
_push_public_key_b64: str | None = None


def _get_push_key_pair() -> tuple[Ed25519PrivateKey, str]:
    global _push_private_key, _push_public_key_b64
    if _push_private_key is not None and _push_public_key_b64 is not None:
        return _push_private_key, _push_public_key_b64

    raw_b64 = os.environ.get(_PUSH_PRIVATE_KEY_ENV, "")
    if not raw_b64:
        raise RuntimeError(f"{_PUSH_PRIVATE_KEY_ENV} is not set")
    try:
        seed = base64.b64decode(raw_b64)
        _push_private_key = Ed25519PrivateKey.from_private_bytes(seed)
    except (binascii.Error, ValueError) as e:
        raise RuntimeError(
            f"{_PUSH_PRIVATE_KEY_ENV} is not a valid base64-encoded "
            f"32-byte Ed25519 seed: {e}"
        ) from e
    pub_bytes = _push_private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    _push_public_key_b64 = base64.b64encode(pub_bytes).decode()
    return _push_private_key, _push_public_key_b64


def _sign_sidecar_request(path: str, sha256_hex: str) -> tuple[str, str]:
    """Sign a sidecar request and return (signature_b64, timestamp).

    Signs {timestamp}|{path}|{sha256_hex} with the Ed25519 private key.
    Used for both push (path=mount_path, sha256_hex=bundle SHA)
    and snapshot endpoints (path=endpoint_path, sha256_hex=body SHA).
    """
    priv_key, _ = _get_push_key_pair()
    ts = str(int(time.time()))
    message = f"{ts}|{path}|{sha256_hex}".encode()
    sig = priv_key.sign(message)
    return base64.b64encode(sig).decode(), ts


_MAX_BUNDLE_BYTES = 100 * 1024 * 1024  # 100 MiB


def _build_targz(files: FileSet) -> tuple[bytes, str]:
    total = sum(len(v) for v in files.values())
    if total > _MAX_BUNDLE_BYTES:
        raise FatalWriteError(
            f"Bundle size {total} exceeds {_MAX_BUNDLE_BYTES} byte limit"
        )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def _build_nextjs_start_script(
    session_path: str,
    nextjs_port: int,
    check_node_modules: bool = False,
) -> str:
    """Build shell script to start the NextJS dev server.

    Args:
        session_path: Path to the session directory (should be shell-safe)
        nextjs_port: Port number for the NextJS dev server
        check_node_modules: If True, check for node_modules and run bun install if missing

    Returns:
        Shell script string to start the NextJS server
    """
    install_check = ""
    if check_node_modules:
        install_check = f"""
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies with bun..."
    BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
fi
"""

    return f"""
set -e
cd {session_path}/outputs/web
{install_check}
echo "Starting Next.js dev server on port {nextjs_port}..."
nohup bun run dev -- -p {nextjs_port} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
"""


class KubernetesSandboxManager(SandboxManager):
    """Kubernetes-based sandbox manager for production deployments.

    Manages sandboxes as Kubernetes pods with:
    - Main sandbox container running Next.js + opencode agent
    - S3-based snapshots via AWS CLI in the sandbox container
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

        # Load AGENTS.md template path
        build_dir = Path(__file__).parent.parent.parent  # /onyx/server/features/build/
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"

        logger.info(
            "KubernetesSandboxManager initialized: namespace=%s, image=%s",
            self._namespace,
            self._image,
        )

    def _get_pod_name(self, sandbox_id: str | UUID) -> str:
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
        skills_section: str,
        provider: str | None = None,
        model_name: str | None = None,
        nextjs_port: int | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> str:
        """Load and populate agent instructions from template file."""
        return generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_section=skills_section,
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port,
            disabled_tools=disabled_tools,
            user_name=user_name,
            user_role=user_role,
        )

    def _create_sandbox_pod(
        self,
        sandbox_id: str,
        tenant_id: str,
        onyx_pat: str,
    ) -> client.V1Pod:
        """Create Pod specification for sandbox (user-level).

        Creates pod with:
        - sessions/ directory for per-session workspaces

        NOTE: Session-specific setup is done via setup_session_workspace().
        """
        pod_name = self._get_pod_name(sandbox_id)

        # Sandbox container — runs the agent. No IRSA (skip-containers annotation
        # on the SA strips AWS env vars and the projected token from this container).
        sandbox_ports = [
            client.V1ContainerPort(name="agent", container_port=AGENT_PORT),
        ]
        for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
            sandbox_ports.append(
                client.V1ContainerPort(name=f"nextjs-{port}", container_port=port)
            )

        sandbox_container = client.V1Container(
            name="sandbox",
            image=self._image,
            image_pull_policy="IfNotPresent",
            command=["/workspace/entrypoint.sh"],
            ports=sandbox_ports,
            env=[
                client.V1EnvVar(name="ONYX_PAT", value=onyx_pat),
                client.V1EnvVar(name="ONYX_SERVER_URL", value=SANDBOX_API_SERVER_URL),
            ],
            volume_mounts=[
                client.V1VolumeMount(
                    name="workspace", mount_path="/workspace/sessions"
                ),
                client.V1VolumeMount(
                    name="managed", mount_path="/workspace/managed", read_only=True
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={
                    "cpu": SANDBOX_POD_CPU_REQUEST,
                    "memory": SANDBOX_POD_MEMORY_REQUEST,
                },
                limits={
                    "cpu": SANDBOX_POD_CPU_LIMIT,
                    "memory": SANDBOX_POD_MEMORY_LIMIT,
                },
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=False,
                privileged=False,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )

        # Sidecar container — runs the push daemon + snapshot API on port 8731.
        # Receives IRSA credentials for S3 access in prod; falls back to
        # forwarded AWS_* / AWS_ENDPOINT_URL from the api_server env in
        # local-dev / CI where IRSA isn't available and an S3-compatible
        # service (e.g. minio) is reachable in-cluster.
        _, push_public_key_b64 = _get_push_key_pair()
        sidecar_env = [
            client.V1EnvVar(name=_PUSH_PUBLIC_KEY_ENV, value=push_public_key_b64),
        ]
        for var in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "AWS_ENDPOINT_URL",
        ):
            value = os.environ.get(var)
            if value:
                sidecar_env.append(client.V1EnvVar(name=var, value=value))

        # s5cmd v2.3.0 reads S3_ENDPOINT_URL — it does NOT honor
        # AWS_ENDPOINT_URL. Mirror AWS_ENDPOINT_URL into S3_ENDPOINT_URL
        # so the snapshot daemon's `s5cmd pipe`/`cat` and the file-sync
        # sidecar's `s5cmd sync` both hit MinIO in dev/CI.
        #
        # We do NOT forward the api_server's own S3_ENDPOINT_URL: in CI
        # that points at a host-network MinIO (localhost:9004 from
        # docker-compose) which is unreachable from inside the pod. The
        # cluster-DNS-reachable endpoint is always in AWS_ENDPOINT_URL.
        aws_endpoint = os.environ.get("AWS_ENDPOINT_URL")
        if aws_endpoint:
            sidecar_env.append(
                client.V1EnvVar(name="S3_ENDPOINT_URL", value=aws_endpoint)
            )
        sidecar_container = client.V1Container(
            name="sidecar",
            image=self._image,
            image_pull_policy="IfNotPresent",
            command=["/workspace/sidecar-entrypoint.sh"],
            ports=[
                client.V1ContainerPort(
                    name="push-daemon", container_port=PUSH_DAEMON_PORT
                ),
            ],
            env=sidecar_env,
            volume_mounts=[
                client.V1VolumeMount(
                    name="workspace", mount_path="/workspace/sessions"
                ),
                client.V1VolumeMount(name="managed", mount_path="/workspace/managed"),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": "500m", "memory": "512Mi"},
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=False,
                privileged=False,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
            liveness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=PUSH_DAEMON_PORT),
                initial_delay_seconds=5,
                period_seconds=30,
            ),
            readiness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=PUSH_DAEMON_PORT),
                initial_delay_seconds=3,
                period_seconds=10,
            ),
        )

        volumes = [
            client.V1Volume(
                name="workspace",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="50Gi"),
            ),
            client.V1Volume(
                name="managed",
                empty_dir=client.V1EmptyDirVolumeSource(size_limit="5Gi"),
            ),
        ]

        pod_spec = client.V1PodSpec(
            service_account_name=self._service_account,
            containers=[sandbox_container, sidecar_container],
            share_process_namespace=False,
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
                    "admission.datadoghq.com/enabled": "false",
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

    def _ensure_service_exists(
        self,
        sandbox_id: UUID,
        tenant_id: str,
    ) -> None:
        """Ensure a ClusterIP service exists for the sandbox pod.

        Handles the case where a service is in Terminating state (has a
        deletion_timestamp) by waiting for deletion and recreating it.
        This prevents a race condition where provision reuses an existing pod
        but the old service is still being deleted.
        """
        service_name = self._get_service_name(str(sandbox_id))

        try:
            svc = self._core_api.read_namespaced_service(
                name=service_name,
                namespace=self._namespace,
            )
            # Service exists - check if it's being deleted
            if svc.metadata.deletion_timestamp:
                logger.info(
                    "Service %s is terminating, waiting for deletion", service_name
                )
                self._wait_for_resource_deletion("service", service_name)
                # Now create a fresh service
                service = self._create_sandbox_service(sandbox_id, tenant_id)
                self._core_api.create_namespaced_service(
                    namespace=self._namespace,
                    body=service,
                )
                logger.info("Recreated Service %s after termination", service_name)
            else:
                logger.debug("Service %s already exists and is active", service_name)

        except ApiException as e:
            if e.status == 404:
                # Service doesn't exist, create it
                logger.info("Creating missing Service %s", service_name)
                service = self._create_sandbox_service(sandbox_id, tenant_id)
                try:
                    self._core_api.create_namespaced_service(
                        namespace=self._namespace,
                        body=service,
                    )
                except ApiException as svc_e:
                    if svc_e.status != 409:  # Ignore AlreadyExists
                        raise
                    logger.debug(
                        "Service %s was created by another request", service_name
                    )
            else:
                raise

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
                        return f"Init container '{container_name}' is in '{reason}' state. Message: {message}"

        return None

    def _pod_ready_poll_intervals(self) -> Iterator[float]:
        """Yield poll intervals according to ``POD_READY_POLL_SCHEDULE``.

        Fast-path detection in the first few seconds (pods usually transition
        Pending→Running→Ready in 12–18s), then back off so a stuck pod
        doesn't hammer the API server.
        """
        for count, interval in POD_READY_POLL_SCHEDULE:
            for _ in range(count):
                yield interval

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
        poll_intervals = self._pod_ready_poll_intervals()

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
                        f"Pod {pod_name} completed unexpectedly (sandbox pods should run indefinitely)"
                    )

                # Check if running and ready
                if phase == "Running":
                    conditions = pod.status.conditions or []
                    for condition in conditions:
                        if condition.type == "Ready" and condition.status == "True":
                            logger.info("Pod %s is ready", pod_name)
                            return True

                logger.debug("Pod %s status: %s, waiting...", pod_name, phase)

            except ApiException as e:
                if e.status == 404:
                    raise RuntimeError(f"Pod {pod_name} was deleted")
                logger.warning("Error checking pod status: %s", e)

            time.sleep(next(poll_intervals, 2.0))

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

        logger.warning("Timeout waiting for pod %s to become ready", pod_name)
        return False

    def _pod_exists_and_healthy(self, pod_name: str) -> bool:
        """Check if a pod exists and is in a healthy/running state.

        Args:
            pod_name: Name of the pod to check

        Returns:
            True if pod exists and is running/ready, False otherwise
        """
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            phase = pod.status.phase

            # Check if running and ready
            if phase == "Running":
                conditions = pod.status.conditions or []
                for condition in conditions:
                    if condition.type == "Ready" and condition.status == "True":
                        return True

            # Pending is OK too - pod is being created by another request
            if phase == "Pending":
                return True

            return False
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,  # noqa: ARG002
        onyx_pat: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox as a Kubernetes pod (user-level).

        This method is idempotent - if a pod already exists and is healthy,
        it will be reused. This prevents race conditions when multiple requests
        try to provision the same sandbox concurrently.

        Creates pod with:
        1. Sessions/ directory for per-session workspaces
        2. Main container runs the sandbox environment

        NOTE: This does NOT set up session-specific workspaces.
        Call setup_session_workspace() to create session workspaces.

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            llm_config: LLM provider configuration
            onyx_pat: Raw PAT token to inject as ONYX_PAT env var in the pod

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        logger.info(
            "Starting Kubernetes sandbox provisioning for sandbox %s, user %s, tenant %s",
            sandbox_id,
            user_id,
            tenant_id,
        )

        pod_name = self._get_pod_name(str(sandbox_id))

        # Check if pod already exists and is healthy (idempotency check)
        if self._pod_exists_and_healthy(pod_name):
            logger.info(
                "Pod %s already exists and is healthy, reusing existing pod", pod_name
            )
            # Ensure service exists and is not terminating
            self._ensure_service_exists(sandbox_id, tenant_id)

            # Wait for pod to be ready if it's still pending
            logger.info("Waiting for existing pod %s to become ready...", pod_name)
            if not self._wait_for_pod_ready(pod_name):
                raise RuntimeError(
                    f"Timeout waiting for existing sandbox pod {pod_name} to become ready"
                )

            logger.info(
                "Reusing existing Kubernetes sandbox %s, pod: %s", sandbox_id, pod_name
            )
            return SandboxInfo(
                sandbox_id=sandbox_id,
                directory_path=f"k8s://{self._namespace}/{pod_name}",
                status=SandboxStatus.RUNNING,
                last_heartbeat=None,
            )

        if not onyx_pat:
            raise ValueError("onyx_pat is required for Kubernetes sandbox provisioning")
        if not SANDBOX_API_SERVER_URL:
            raise ValueError(
                "SANDBOX_API_SERVER_URL must be set for Kubernetes sandbox provisioning"
            )

        try:
            # 1. Create Pod (user-level only, no session setup)
            logger.debug("Creating Pod %s", pod_name)
            pod = self._create_sandbox_pod(
                sandbox_id=str(sandbox_id),
                tenant_id=tenant_id,
                onyx_pat=onyx_pat,
            )
            try:
                self._core_api.create_namespaced_pod(
                    namespace=self._namespace,
                    body=pod,
                )
            except ApiException as e:
                if e.status == 409:
                    # Pod was created by another concurrent request
                    # Check if it's healthy and reuse it
                    logger.warning(
                        "Pod %s already exists (409 conflict, this shouldn't normally happen), checking if it's healthy...",
                        pod_name,
                    )
                    if self._pod_exists_and_healthy(pod_name):
                        logger.warning(
                            "During provisioning, discovered that pod %s already exists. Reusing",
                            pod_name,
                        )
                        # Continue to ensure service exists and wait for ready
                    else:
                        # Pod exists but is not healthy - this shouldn't happen often
                        # but could occur if a previous provision failed mid-way
                        logger.warning(
                            "Pod %s exists but is not healthy, waiting for it to become ready or fail",
                            pod_name,
                        )
                else:
                    raise

            # 2. Create Service (handles terminating services)
            self._ensure_service_exists(sandbox_id, tenant_id)

            # 3. Wait for pod to be ready
            logger.info("Waiting for pod %s to become ready...", pod_name)
            if not self._wait_for_pod_ready(pod_name):
                raise RuntimeError(
                    f"Timeout waiting for sandbox pod {pod_name} to become ready"
                )

            logger.info(
                "Provisioned Kubernetes sandbox %s, pod: %s (no sessions yet)",
                sandbox_id,
                pod_name,
            )

            return SandboxInfo(
                sandbox_id=sandbox_id,
                directory_path=f"k8s://{self._namespace}/{pod_name}",
                status=SandboxStatus.RUNNING,
                last_heartbeat=None,
            )

        except Exception as e:
            # Only cleanup if we're sure the pod is not being used by another request
            # Check if pod is healthy - if so, don't clean up (another request may own it)
            if self._pod_exists_and_healthy(pod_name):
                logger.warning(
                    "Kubernetes sandbox provisioning failed for sandbox %s: %s, but pod is healthy (likely owned by concurrent request), not cleaning up",
                    sandbox_id,
                    e,
                )
            else:
                logger.error(
                    "Kubernetes sandbox provisioning failed for sandbox %s: %s",
                    sandbox_id,
                    e,
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
                logger.debug("Waiting for %s %s to be deleted...", resource_type, name)
                time.sleep(RESOURCE_DELETION_POLL_INTERVAL_SECONDS)

            except ApiException as e:
                if e.status == 404:
                    # Resource is gone
                    logger.debug(
                        "%s %s fully deleted", resource_type.capitalize(), name
                    )
                    return True
                # Other error, log and continue waiting
                logger.warning(
                    "Error checking %s %s status: %s", resource_type, name, e
                )
                time.sleep(RESOURCE_DELETION_POLL_INTERVAL_SECONDS)

        logger.warning(
            "Timeout waiting for %s %s to be deleted after %ss",
            resource_type,
            name,
            timeout,
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
            logger.debug("Deleted Service %s", service_name)
            service_deleted = True
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                service_deleted = True
            else:
                logger.error("Error deleting Service %s: %s", service_name, e)
                raise

        pod_deleted = False
        try:
            self._core_api.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            logger.debug("Deleted Pod %s", pod_name)
            pod_deleted = True
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                pod_deleted = True
            else:
                logger.error("Error deleting Pod %s: %s", pod_name, e)
                raise

        # Wait for resources to be fully deleted to prevent 409 conflicts
        # on immediate re-provisioning
        if wait_for_deletion:
            if service_deleted:
                self._wait_for_resource_deletion("service", service_name)
            if pod_deleted:
                self._wait_for_resource_deletion("pod", pod_name)

    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up Kubernetes resources.

        Removes session mappings for this sandbox, then deletes the
        Service and Pod. ACP clients are ephemeral (created per message),
        so there's nothing to stop here.

        Args:
            sandbox_id: The sandbox ID to terminate
        """
        # Clean up Kubernetes resources (needs string for pod/service names)
        self._cleanup_kubernetes_resources(str(sandbox_id))

        logger.info("Terminated Kubernetes sandbox %s", sandbox_id)

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
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
        5. Start Next.js dev server (skipped when ``nextjs_port`` is None,
           e.g. for headless scheduled-task fires that don't need a preview).

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            snapshot_path: Optional S3 path - logged but ignored (no S3 access)
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md

        Raises:
            RuntimeError: If workspace setup fails
        """
        if snapshot_path:
            logger.warning(
                "Snapshot restoration requested but not supported in Kubernetes mode. Snapshot path %s will be ignored. Session %s will start with fresh outputs template.",
                snapshot_path,
                session_id,
            )

        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        # Paths inside the pod (created during workspace setup below):
        # - {session_path}/attachments: user-uploaded files
        #
        # Attachments section is injected dynamically when first file is uploaded.
        agent_instructions = self._load_agent_instructions(
            skills_section=skills_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
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
echo "Copying outputs template"
if [ -d /workspace/templates/outputs ]; then
    cp -r /workspace/templates/outputs/* {session_path}/outputs/
    # flock+sentinel: serialize concurrent session setups; .ready guards
    # against a partial cp from a previous interrupted run.
    (
        flock -x 9
        if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
            echo "Bootstrapping bun cache on workspace volume..."
            rm -rf {BUN_CACHE_DIR}
            cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \\
                || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
            touch {BUN_CACHE_DIR}/.ready
        fi
    ) 9>{BUN_CACHE_DIR}.lock
    cd {session_path}/outputs/web && \\
        BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
else
    echo "Warning: outputs template not found at /workspace/templates/outputs"
    mkdir -p {session_path}/outputs/web
fi
"""

        # Headless callers (scheduled tasks) pass nextjs_port=None — the
        # agent's tools work without a dev server.
        nextjs_start_script = (
            _build_nextjs_start_script(
                session_path, nextjs_port, check_node_modules=False
            )
            if nextjs_port is not None
            else ""
        )

        setup_script = f"""
set -e

# Create session directory structure
echo "Creating session directory: {session_path}"
mkdir -p {session_path}/outputs
mkdir -p {session_path}/attachments

# Setup outputs
{outputs_setup}

# DO NOT mkdir /workspace/managed/skills or /workspace/managed/user_library
# here — the push daemon swaps these paths via os.rename(symlink, mount),
# which fails if the mount is a real directory. Dangling until the first
# push lands is fine; nothing reads these during the rest of setup.
mkdir -p {session_path}/.opencode
ln -sf /workspace/managed/skills {session_path}/.opencode/skills
echo "Linked skills to /workspace/managed/skills"
ln -sf /workspace/managed/user_library {session_path}/user_library
echo "Linked user_library to /workspace/managed/user_library"

# Write agent instructions
echo "Writing AGENTS.md"
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md

# Write opencode config
echo "Writing opencode.json"
printf '%s' '{opencode_json_escaped}' > {session_path}/opencode.json

# Start Next.js dev server
{nextjs_start_script}

echo "Session workspace setup complete"
"""

        logger.info(
            "Setting up session workspace %s in sandbox %s", session_id, sandbox_id
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

            logger.debug("Session setup output: %s", exec_response)
            logger.info(
                "Set up session workspace %s in sandbox %s", session_id, sandbox_id
            )

        except Exception as e:
            logger.error(
                "Failed to setup session workspace %s in sandbox %s: %s",
                session_id,
                sandbox_id,
                e,
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to setup session workspace {session_id}: {e}"
            ) from e

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,  # noqa: ARG002
    ) -> None:
        """Clean up a session workspace (on session delete).

        Removes the ACP session mapping and executes kubectl exec to remove
        the session directory. The shared ACP client persists for other sessions.

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
            "Cleaning up session workspace %s in sandbox %s", session_id, sandbox_id
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

            logger.debug("Session cleanup output: %s", exec_response)
            logger.info(
                "Cleaned up session workspace %s in sandbox %s", session_id, sandbox_id
            )

        except ApiException as e:
            if e.status == 404:
                # Pod not found, nothing to clean up
                logger.debug("Pod %s not found, skipping cleanup", pod_name)
            else:
                logger.warning(
                    "Error cleaning up session workspace %s: %s", session_id, e
                )
        except Exception as e:
            logger.warning("Error cleaning up session workspace %s: %s", session_id, e)

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        """Create a snapshot via the sidecar's /snapshot/create endpoint.

        Captures:
        - sessions/$session_id/outputs/
        - sessions/$session_id/attachments/
        - sessions/$session_id/.opencode-data/

        Returns None if there are no outputs to snapshot.
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        snapshot_id = uuid4()

        try:
            pod_ip = self._get_pod_ip(pod_name)
        except (FatalWriteError, RetriableWriteError) as e:
            raise RuntimeError(f"Failed to create snapshot: {e}") from e

        body = (
            SnapshotCreateRequest(
                session_id=session_id,
                tenant_id=tenant_id,
                s3_bucket=self._s3_bucket,
                snapshot_id=snapshot_id,
            )
            .model_dump_json()
            .encode()
        )

        try:
            resp = self._post_to_sidecar(
                pod_ip, "/snapshot/create", body, timeout=300.0
            )
        except httpx.TransportError as e:
            raise RuntimeError(f"Snapshot create request failed: {e}") from e

        if resp.status_code != 200:
            raise RuntimeError(
                f"Snapshot create failed: {resp.status_code} {resp.text}"
            )

        parsed = SnapshotCreateResponse.model_validate_json(resp.content)
        if parsed.status == "empty":
            logger.info("No outputs to snapshot for session %s", session_id)
            return None

        logger.info("Created snapshot for session %s", session_id)
        return SnapshotResult(
            storage_path=parsed.storage_path,
            size_bytes=parsed.size_bytes,
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
            f'[ -d "{session_path}" ] && echo "WORKSPACE_FOUND" || echo "WORKSPACE_MISSING"',
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

            result = "WORKSPACE_FOUND" in resp
            logger.info(
                "[WORKSPACE_CHECK] session=%s, path=%s, raw_resp=%r, result=%s",
                session_id,
                session_path,
                resp,
                result,
            )
            return result

        except ApiException as e:
            logger.warning(
                "Failed to check session workspace exists for %s: %s", session_id, e
            )
            return False

    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        """List UUID session directories under /workspace/sessions/ in the pod.

        Used by idle cleanup to discover sessions that need snapshotting.
        Non-UUID directory names are silently filtered out.
        """
        pod_name = self._get_pod_name(str(sandbox_id))

        exec_command = [
            "/bin/sh",
            "-c",
            'ls -1 /workspace/sessions/ 2>/dev/null || echo ""',
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
        except ApiException as e:
            logger.warning(
                "Failed to list session directories for sandbox %s: %s",
                sandbox_id,
                e,
            )
            return []

        result: list[UUID] = []
        for raw_line in resp.strip().split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            try:
                result.append(UUID(line))
            except ValueError:
                continue
        return result

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
    ) -> None:
        """Download snapshot from S3 via s5cmd, extract, regenerate config, and start NextJS.

        Steps:
        1. Download snapshot from S3 via s5cmd cat in the sandbox container
        2. Pipe directly to tar for extraction
        3. Regenerate configuration files (AGENTS.md, opencode.json)
        4. Start the NextJS dev server (skipped when ``nextjs_port`` is None,
           e.g. for headless scheduled-task fires that don't attach a preview).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in S3 (relative path)
            tenant_id: Tenant identifier for storage access
            nextjs_port: Port number for the NextJS dev server, or None to
                skip starting it.
            llm_config: LLM provider configuration for opencode.json

        Raises:
            RuntimeError: If snapshot restoration fails
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"
        safe_session_path = shlex.quote(session_path)

        try:
            pod_ip = self._get_pod_ip(pod_name)
        except (FatalWriteError, RetriableWriteError) as e:
            raise RuntimeError(f"Failed to restore snapshot: {e}") from e

        body = (
            SnapshotRestoreRequest(
                session_id=session_id,
                tenant_id=tenant_id,
                s3_bucket=self._s3_bucket,
                storage_path=snapshot_storage_path,
            )
            .model_dump_json()
            .encode()
        )

        try:
            resp = self._post_to_sidecar(
                pod_ip, "/snapshot/restore", body, timeout=300.0
            )
        except httpx.TransportError as e:
            raise RuntimeError(f"Snapshot restore request failed: {e}") from e

        if resp.status_code != 204:
            raise RuntimeError(
                f"Snapshot restore failed: {resp.status_code} {resp.text}"
            )

        try:
            # Regenerate configuration files that aren't in the snapshot.
            self._regenerate_session_config(
                pod_name=pod_name,
                session_path=safe_session_path,
                llm_config=llm_config,
                nextjs_port=nextjs_port,
                skills_section=skills_section,
            )

            if nextjs_port is not None:
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
        except ApiException as e:
            raise RuntimeError(f"Failed to restore snapshot: {e}") from e

    def _regenerate_session_config(
        self,
        pod_name: str,
        session_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
    ) -> None:
        """Regenerate session configuration files after snapshot restore.

        Creates:
        - AGENTS.md (agent instructions)
        - opencode.json (LLM configuration)

        Args:
            pod_name: The pod name to exec into
            session_path: Path to the session directory (already shlex.quoted)
            llm_config: LLM provider configuration
            nextjs_port: Port for NextJS (used in AGENTS.md). None when the
                dev server is intentionally skipped — the template renders
                "Unknown" in that case.
        """
        agent_instructions = self._load_agent_instructions(
            skills_section=skills_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=None,
            user_role=None,
        )

        # Generate opencode.json
        opencode_config = build_opencode_config(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            api_key=llm_config.api_key if llm_config.api_key else None,
            api_base=llm_config.api_base,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
        )
        opencode_json = json.dumps(opencode_config)

        # Escape for shell (single quotes)
        opencode_json_escaped = opencode_json.replace("'", "'\\''")
        agent_instructions_escaped = agent_instructions.replace("'", "'\\''")

        # Snapshot tar only carries outputs/, attachments/, .opencode-data/ —
        # re-link the managed-tree symlinks that setup_session_workspace creates.
        config_script = f"""
set -e
mkdir -p {session_path}/.opencode
ln -sfn /workspace/managed/skills {session_path}/.opencode/skills
ln -sfn /workspace/managed/user_library {session_path}/user_library
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md
printf '%s' '{opencode_json_escaped}' > {session_path}/opencode.json
"""

        logger.info("Regenerating session configuration files")
        k8s_stream(
            self._stream_core_api.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=self._namespace,
            container="sandbox",
            command=["/bin/sh", "-c", config_script],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        logger.info("Session configuration files regenerated")

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check if the sidecar's /health endpoint responds."""
        pod_name = self._get_pod_name(str(sandbox_id))
        try:
            pod_ip = self._get_pod_ip(pod_name)
        except (FatalWriteError, RetriableWriteError):
            return False

        url = f"http://{pod_ip}:{PUSH_DAEMON_PORT}/health"
        try:
            with httpx.Client(timeout=timeout) as http_client:
                resp = http_client.get(url)
            return resp.status_code == 200
        except httpx.TransportError:
            return False

    def _create_ephemeral_acp_client(
        self, sandbox_id: UUID, session_path: str
    ) -> ACPExecClient:
        """Create a new ephemeral ACP client for a single message exchange.

        Each call starts a fresh `opencode acp` process in the sandbox pod.
        The process is short-lived — stopped after the message completes.
        This prevents the bug where multiple long-lived processes (one per
        API replica) operate on the same session's flat file storage
        concurrently, causing the JSON-RPC response to be silently lost.

        Args:
            sandbox_id: The sandbox ID
            session_path: Working directory for the session (e.g. /workspace/sessions/{id}).
                XDG_DATA_HOME is set relative to this so opencode's session data
                lives inside the snapshot directory.

        Returns:
            A running ACPExecClient (caller must stop it when done)
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        acp_client = ACPExecClient(
            pod_name=pod_name,
            namespace=self._namespace,
            container="sandbox",
        )
        acp_client.start(cwd=session_path)

        logger.info(
            "[SANDBOX-ACP] Created ephemeral ACP client: sandbox=%s pod=%s api_pod=%s",
            sandbox_id,
            pod_name,
            _API_SERVER_HOSTNAME,
        )
        return acp_client

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream ACP events.

        Creates an ephemeral `opencode acp` process for each message.
        The process resumes the session from opencode's on-disk storage,
        handles the prompt, then is stopped. This ensures only one process
        operates on a session's flat files at a time, preventing the bug
        where multiple long-lived processes (one per API replica) corrupt
        each other's in-memory state.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID (determines workspace directory)
            message: The message content to send

        Yields:
            Typed ACP schema event objects
        """
        packet_logger = get_packet_logger()
        session_path = f"/workspace/sessions/{session_id}"

        # Create an ephemeral ACP client for this message
        acp_client = self._create_ephemeral_acp_client(sandbox_id, session_path)

        try:
            # Resume (or create) the ACP session from opencode's on-disk storage
            acp_session_id = acp_client.resume_or_create_session(cwd=session_path)

            logger.info(
                "[SANDBOX-ACP] Sending message: session=%s acp_session=%s api_pod=%s",
                session_id,
                acp_session_id,
                _API_SERVER_HOSTNAME,
            )

            # Log the send_message call at sandbox manager level
            packet_logger.log_session_start(session_id, sandbox_id, message)

            events_count = 0
            got_prompt_response = False
            try:
                for event in acp_client.send_message(
                    message, session_id=acp_session_id
                ):
                    events_count += 1
                    if isinstance(event, PromptResponse):
                        got_prompt_response = True
                    yield event

                logger.info(
                    "[SANDBOX-ACP] send_message completed: session=%s events=%s got_prompt_response=%s",
                    session_id,
                    events_count,
                    got_prompt_response,
                )
                packet_logger.log_session_end(
                    session_id, success=True, events_count=events_count
                )
            except GeneratorExit:
                logger.warning(
                    "[SANDBOX-ACP] GeneratorExit: session=%s events=%s, sending session/cancel",
                    session_id,
                    events_count,
                )
                try:
                    acp_client.cancel(session_id=acp_session_id)
                except Exception as cancel_err:
                    logger.warning(
                        "[SANDBOX-ACP] session/cancel failed on GeneratorExit: %s",
                        cancel_err,
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error="GeneratorExit: Client disconnected or stream closed by consumer",
                    events_count=events_count,
                )
                raise
            except Exception as e:
                logger.error(
                    "[SANDBOX-ACP] Exception: session=%s events=%s error=%s, sending session/cancel",
                    session_id,
                    events_count,
                    e,
                )
                try:
                    acp_client.cancel(session_id=acp_session_id)
                except Exception as cancel_err:
                    logger.warning(
                        "[SANDBOX-ACP] session/cancel failed on Exception: %s",
                        cancel_err,
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error=f"Exception: {str(e)}",
                    events_count=events_count,
                )
                raise
            except BaseException as e:
                logger.error(
                    "[SANDBOX-ACP] %s: session=%s error=%s",
                    type(e).__name__,
                    session_id,
                    e,
                )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error=f"{type(e).__name__}: {str(e) if str(e) else 'System-level interruption'}",
                    events_count=events_count,
                )
                raise
        finally:
            # Always stop the ephemeral ACP client to kill the opencode process.
            # This ensures no stale processes linger in the sandbox container.
            try:
                acp_client.stop()
            except Exception as e:
                logger.warning(
                    "[SANDBOX-ACP] Failed to stop ephemeral ACP client: session=%s error=%s",
                    session_id,
                    e,
                )

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

        logger.info("Listing directory %s in pod %s", target_path, pod_name)

        # Use exec to list directory
        # -L follows symlinks
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

        logger.debug("Parsing %s lines of ls output for %s", len(lines), base_path)

        for line in lines:
            logger.debug("Parsing line: %s", line)

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
            # in our sandbox setup)
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
                logger.error("Failed to decode base64 content: %s", e)
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

    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        """Convert PPTX to slide images using soffice + pdftoppm in the pod.

        Runs preview.py in the sandbox container which:
        1. Checks if cached slides exist and are newer than the PPTX
        2. If not, converts PPTX -> PDF -> JPEG slides
        3. Returns list of slide image paths
        """
        pod_name = self._get_pod_name(str(sandbox_id))

        # Security: sanitize paths
        pptx_path_obj = Path(pptx_path.lstrip("/"))
        pptx_clean_parts = [p for p in pptx_path_obj.parts if p != ".."]
        clean_pptx = str(Path(*pptx_clean_parts)) if pptx_clean_parts else "."

        cache_path_obj = Path(cache_dir.lstrip("/"))
        cache_clean_parts = [p for p in cache_path_obj.parts if p != ".."]
        clean_cache = str(Path(*cache_clean_parts)) if cache_clean_parts else "."

        session_root = f"/workspace/sessions/{session_id}"
        pptx_abs = f"{session_root}/{clean_pptx}"
        cache_abs = f"{session_root}/{clean_cache}"

        exec_command = [
            "python",
            "/workspace/managed/skills/pptx/scripts/preview.py",
            pptx_abs,
            cache_abs,
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

            lines = [line.strip() for line in resp.strip().split("\n") if line.strip()]

            if not lines:
                raise ValueError("Empty response from PPTX conversion")

            if lines[0] == "ERROR_NOT_FOUND":
                raise ValueError(f"File not found: {pptx_path}")

            if lines[0] == "ERROR_NO_PDF":
                raise ValueError("soffice did not produce a PDF file")

            cached = lines[0] == "CACHED"
            # Skip the status line, rest are file paths
            abs_paths = lines[1:] if lines[0] in ("CACHED", "GENERATED") else lines

            # Convert absolute paths to session-relative paths
            prefix = f"{session_root}/"
            rel_paths = []
            for p in abs_paths:
                if p.startswith(prefix):
                    rel_paths.append(p[len(prefix) :])
                elif p.endswith(".jpg"):
                    rel_paths.append(p)

            return (rel_paths, cached)

        except ApiException as e:
            raise RuntimeError(f"Failed to generate PPTX preview: {e}") from e

    def _ensure_agents_md_attachments_section(
        self, sandbox_id: UUID, session_id: UUID
    ) -> None:
        """Ensure AGENTS.md has the attachments section.

        Called after uploading a file. Only adds the section if it doesn't exist.
        Inserts the section above ## Skills for better document flow.
        This is a fire-and-forget operation - failures are logged but not raised.
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"
        agents_md_path = f"{session_path}/AGENTS.md"

        # Base64 encode the content for safe shell handling
        attachments_content_b64 = base64.b64encode(
            ATTACHMENTS_SECTION_CONTENT.encode()
        ).decode()

        # Script: add section before ## Skills if not present
        # Uses a temp file approach for safe insertion
        script = f"""
if [ -f "{agents_md_path}" ]; then
    if ! grep -q "## Attachments (PRIORITY)" "{agents_md_path}" 2>/dev/null; then
        # Check if ## Skills exists
        if grep -q "## Skills" "{agents_md_path}" 2>/dev/null; then
            # Insert before ## Skills using awk
            awk -v content="$(echo "{attachments_content_b64}" | base64 -d)" '
                /^## Skills/ {{ print content; print ""; }}
                {{ print }}
            ' "{agents_md_path}" > "{agents_md_path}.tmp" && mv "{agents_md_path}.tmp" "{agents_md_path}"
            echo "ADDED_BEFORE_SKILLS"
        else
            # Fallback: append to end
            echo "" >> "{agents_md_path}"
            echo "" >> "{agents_md_path}"
            echo "{attachments_content_b64}" | base64 -d >> "{agents_md_path}"
            echo "ADDED_AT_END"
        fi
    else
        echo "EXISTS"
    fi
else
    echo "NO_AGENTS_MD"
fi
"""

        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", script],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.debug(
                "Ensure AGENTS.md attachments section for session %s: %s",
                session_id,
                resp.strip(),
            )
        except ApiException as e:
            logger.warning("Failed to ensure AGENTS.md attachments section: %s", e)

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload a file to the session's attachments directory.

        Uses tar streaming via stdin with explicit byte count to avoid EOF issues.
        The K8s Python client cannot close stdin without closing the entire WebSocket
        connection, so we use `head -c <size>` to read exactly the expected bytes
        instead of waiting for EOF.

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
        tar_size = len(tar_data)

        # Shell script that:
        # 1. Creates target directory and temp extraction directory
        # 2. Reads exactly tar_size bytes from stdin (avoids needing EOF signal)
        # 3. Extracts tar to temp directory
        # 4. Moves file to target with collision handling
        # 5. Cleans up temp directory
        # 6. Outputs final filename
        script = f"""
set -e
target_dir="{target_dir}"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$target_dir"

# Read exactly {tar_size} bytes and extract (avoids waiting for EOF)
head -c {tar_size} | tar xf - -C "$tmpdir"

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

            # Read response - head -c will read exactly tar_size bytes and proceed,
            # so we don't need to close stdin to signal EOF
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
                logger.warning("Upload stderr: %s", stderr_data.strip())

            # Last line of output is the final filename
            final_filename = stdout_data.strip().split("\n")[-1]

            if not final_filename:
                raise RuntimeError(
                    f"Upload failed - no filename returned. stderr: {stderr_data}"
                )

            logger.info(
                "Uploaded file to session %s: attachments/%s (%s bytes)",
                session_id,
                final_filename,
                len(content),
            )

            # Ensure AGENTS.md has the attachments section
            self._ensure_agents_md_attachments_section(sandbox_id, session_id)

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
                logger.info("Deleted file from session %s: %s", session_id, path)
            else:
                logger.debug(
                    "File not found for deletion in session %s: %s", session_id, path
                )

            return deleted

        except ApiException as e:
            raise RuntimeError(f"Failed to delete file: {e}") from e

    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        if (
            ".." in path
            or path.startswith("/")
            or not re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-./]*$", path)
        ):
            raise ValueError(f"Invalid sandbox file path: {path}")

        pod_name = self._get_pod_name(str(sandbox_id))
        safe_path = shlex.quote(f"/workspace/{path}")
        safe_dir = shlex.quote(f"/workspace/{path}".rsplit("/", 1)[0])
        escaped = content.replace("'", "'\\''")

        script = f"""set -e
mkdir -p {safe_dir}
printf '%s' '{escaped}' > {safe_path}
echo WRITE_OK"""
        try:
            resp = k8s_stream(
                self._stream_core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self._namespace,
                container="sandbox",
                command=["/bin/sh", "-c", script],
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
            )
            if "WRITE_OK" not in resp:
                raise RuntimeError(f"write_sandbox_file failed for {path}: {resp}")
        except ApiException as e:
            raise RuntimeError(f"Failed to write sandbox file {path}: {e}") from e

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
                    logger.warning("Failed to parse upload stats: %s", resp)
                    return 0, 0

            return 0, 0

        except ApiException as e:
            logger.warning("Failed to get upload stats: %s", e)
            return 0, 0

    def _get_pod_ip(self, pod_name: str) -> str:
        """Read pod IP. Raises FatalWriteError on 404, RetriableWriteError otherwise."""
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
        except ApiException as e:
            if e.status == 404:
                raise FatalWriteError(f"Pod {pod_name} not found") from e
            raise RetriableWriteError(f"Failed to read pod {pod_name}: {e}") from e

        pod_ip = pod.status.pod_ip
        if not pod_ip:
            raise RetriableWriteError(f"Pod {pod_name} has no IP yet")
        return pod_ip

    def _post_to_sidecar(
        self, pod_ip: str, endpoint_path: str, body: bytes, timeout: float = 30.0
    ) -> httpx.Response:
        """POST a signed JSON request to a sidecar endpoint."""
        sha256_hex = hashlib.sha256(body).hexdigest()
        sig_b64, ts = _sign_sidecar_request(endpoint_path, sha256_hex)
        url = f"http://{pod_ip}:{PUSH_DAEMON_PORT}{endpoint_path}"
        with httpx.Client(timeout=timeout) as http_client:
            return http_client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Push-Signature": sig_b64,
                    "X-Push-Timestamp": ts,
                },
            )

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        """Build tar.gz, POST to in-pod daemon."""
        pod_name = self._get_pod_name(sandbox_id)
        pod_ip = self._get_pod_ip(pod_name)

        tar_bytes, sha256_hex = _build_targz(files)
        sig_b64, ts = _sign_sidecar_request(mount_path, sha256_hex)

        url = f"http://{pod_ip}:{PUSH_DAEMON_PORT}/push"
        try:
            with httpx.Client(timeout=30.0) as http_client:
                resp = http_client.post(
                    url,
                    params={"mount_path": mount_path},
                    content=tar_bytes,
                    headers={
                        "Content-Type": "application/gzip",
                        "X-Bundle-Sha256": sha256_hex,
                        "X-Push-Signature": sig_b64,
                        "X-Push-Timestamp": ts,
                    },
                )
        except httpx.TransportError as e:
            raise RetriableWriteError(f"Push to {pod_name} failed: {e}") from e

        if resp.status_code == 200:
            return
        err = f"{pod_name}: {resp.status_code} {resp.text}"
        if resp.status_code >= 500:
            raise RetriableWriteError(err)
        raise FatalWriteError(err)
