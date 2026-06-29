"""Kubernetes-based sandbox manager for production deployments.

KubernetesSandboxManager provisions sandboxes as Kubernetes pods with true
container isolation. Each sandbox runs in its own pod with dedicated resources.

Key features:
- Pod-based isolation (not process-level)
- FileStore-backed snapshots streamed through the sidecar filesystem API
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

IMPORTANT: This manager does NOT interface with the database directly. All
database operations should be handled by the caller (SessionManager, Celery
tasks, etc.).

Use get_sandbox_manager() from base.py to get the appropriate implementation.
"""

import base64
import binascii
import copy
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import shlex
import tarfile
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID

from kubernetes import client
from kubernetes import watch
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream as k8s_stream

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import OPENCODE_SERVE_PORT
from onyx.server.features.build.configs import OPENCODE_SERVER_PASSWORD
from onyx.server.features.build.configs import SANDBOX_API_SERVER_URL
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.features.build.configs import SANDBOX_PROXY_HOST
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.configs import SANDBOX_PROXY_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_SERVICE_ACCOUNT_NAME
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR
from onyx.server.features.build.sandbox.base import BUN_IMAGE_CACHE_DIR
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    PUSH_DAEMON_PORT,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_OPENCODE_HISTORY_CREATE_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_OPENCODE_HISTORY_RESTORE_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_PUSH_PUBLIC_KEY_ENV_VAR,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_SNAPSHOT_CREATE_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    sidecar_snapshot_restore_path,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SnapshotCreateRequest,
)
from onyx.server.features.build.sandbox.kubernetes.k8s_client import load_kube_config
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import (
    get_push_key_pair,
)
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import SidecarClient
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import (
    SidecarRequestError,
)
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import (
    SidecarStatusError,
)
from onyx.server.features.build.sandbox.labels import LABEL_K8S_COMPONENT
from onyx.server.features.build.sandbox.labels import LABEL_K8S_COMPONENT_SANDBOX
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY_ONYX
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.labels import LABEL_TENANT_ID
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import RetriableWriteError
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.util.agent_instructions import (
    ATTACHMENTS_SECTION_CONTENT,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_multi_provider_opencode_config,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# API server pod hostname — used to identify which replica is handling a
# request. In K8s, HOSTNAME is set to the pod name (e.g., "api-server-dpgg7").
_API_SERVER_HOSTNAME = os.environ.get("HOSTNAME", "unknown")

POD_READY_TIMEOUT_SECONDS = 60

OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS = 300.0
POD_IP_POLL_INTERVAL_SECONDS = 0.5

# Resource deletion timeout and polling interval
# Kubernetes deletes are async - we need to wait for resources to actually be
# gone.
RESOURCE_DELETION_TIMEOUT_SECONDS = 30
RESOURCE_DELETION_POLL_INTERVAL_SECONDS = 0.5


# Pinned to the proxy IP via pod hostAliases — the iptables lockdown blocks DNS,
# so the sandbox can't resolve it on its own.
_PROXY_ALIAS = "sandbox-proxy"
_SANDBOX_CONTAINER_NAME = "sandbox"
_SIDECAR_CONTAINER_NAME = "sidecar"

# Helm-rendered PodTemplate carrying the static sandbox pod shape.
_PODTEMPLATE_NAME = "sandbox-pod"

# Per-session egress tagging plugin, baked into the sandbox image (see
# docker/Dockerfile). Path must match the COPY destination there.
_OPENCODE_SESSION_TAG_PLUGIN_PATH = "/workspace/opencode-plugins/session-proxy-tag.ts"
# Surfaces the no-op `connect_app` tool; always on. Its "ask" permission is what
# the api-server intercepts to drive the connect-app OAuth flow.
_OPENCODE_CONNECT_APP_PLUGIN_PATH = "/workspace/opencode-plugins/connect-app.ts"


_PROXY_RESOLVE_RETRY_ATTEMPTS = 5
_PROXY_RESOLVE_RETRY_BACKOFF_S = 0.5


def _placeholder_llm_configs(
    configs: list[LLMProviderConfig],
) -> list[LLMProviderConfig]:
    """
    Swaps real LLM keys for the proxy placeholder before the opencode config
    reaches the pod; provider/model/api_base stay so routing is unchanged.
    """
    return [
        c.model_copy(update={"api_key": SANDBOX_PROXY_INJECTED_PLACEHOLDER})
        if c.api_key
        else c
        for c in configs
    ]


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
    """Builds shell script to start the NextJS dev server.

    Args:
        session_path: Path to the session directory (should be shell-safe).
        nextjs_port: Port number for the NextJS dev server.
        check_node_modules: If True, check for node_modules and run bun install
            if missing.

    Returns:
        Shell script string to start the NextJS server.
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
export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/$(basename {session_path})/webapp"
if grep -q "WEBAPP_ASSET_PREFIX" next.config.ts 2>/dev/null; then
    cat > next.config.ts <<'EOF'
import type {{ NextConfig }} from "next";

const webappBasePath = process.env.ONYX_WEBAPP_BASE_PATH || undefined;

const nextConfig: NextConfig = {{
  ...(webappBasePath
    ? {{ basePath: webappBasePath, assetPrefix: webappBasePath }}
    : {{}}),
}};

export default nextConfig;
EOF
fi
echo "Starting Next.js dev server on port {nextjs_port}..."
nohup bun run dev -- -H 0.0.0.0 -p {nextjs_port} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
"""


class KubernetesSandboxManager(SandboxManager):
    """Kubernetes-based sandbox manager for production deployments.

    Manages sandboxes as Kubernetes pods with:
    - Main sandbox container running Next.js + opencode agent
    - FileStore-backed snapshots via sidecar HTTP streaming
    - ClusterIP services for network access

    IMPORTANT: This manager does NOT interface with the database directly.
    All database operations should be handled by the caller.

    This is a singleton class - use get_sandbox_manager() to get the instance.
    """

    supports_opencode_history_persistence = True

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
        load_kube_config()

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
        self._service_account = SANDBOX_SERVICE_ACCOUNT_NAME
        self._snapshot_manager = SnapshotManager(get_default_file_store())
        self._sidecar_client = SidecarClient(
            host=lambda sandbox_id: (
                f"{self._get_pod_name(sandbox_id)}.{self._namespace}.svc.cluster.local"
            )
        )

        self._init_serve_state()

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

    def _get_opencode_secret_name(self, sandbox_id: str | UUID) -> str:
        """Per-pod K8s Secret holding OPENCODE_SERVER_PASSWORD."""
        return f"{self._get_pod_name(sandbox_id)}-opencode-auth"

    _OPENCODE_PASSWORD_SECRET_KEY = "password"
    _OPENCODE_CONFIG_SECRET_KEY = "config"

    def _provision_opencode_secret(self, sandbox_id: str, config_json: str) -> None:
        """Per-pod Secret with ``password`` (HTTP Basic) + ``config``
        (full opencode.json, surfaced as ``OPENCODE_CONFIG_CONTENT``).

        Without ``config``, opencode-serve loads no provider config and
        falls back to its built-in ``opencode/big-pickle`` default.
        """
        secret_name = self._get_opencode_secret_name(sandbox_id)

        def _build_secret(password: str) -> "client.V1Secret":
            return client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=secret_name,
                    namespace=self._namespace,
                    labels={
                        "app.kubernetes.io/component": "sandbox-opencode-auth",
                        "onyx.app/sandbox-id": str(sandbox_id),
                    },
                ),
                type="Opaque",
                string_data={
                    self._OPENCODE_PASSWORD_SECRET_KEY: password,
                    self._OPENCODE_CONFIG_SECRET_KEY: config_json,
                },
            )

        existing_password = self._read_opencode_password(sandbox_id)
        password = existing_password or secrets.token_urlsafe(32)
        try:
            self._core_api.create_namespaced_secret(
                namespace=self._namespace, body=_build_secret(password)
            )
            logger.info("Created opencode secret %s", secret_name)
        except ApiException as e:
            if e.status != 409:
                raise
            # Re-read after 409: the winner's password is the one already
            # bound into the racing pod's env (K8s does not propagate
            # Secret updates to running container env vars), so we must
            # NOT overwrite with our locally-generated value.
            winner_password = self._read_opencode_password(sandbox_id)
            if winner_password is None:
                logger.warning(
                    "opencode secret %s 409'd on create but read None on "
                    "follow-up — Secret may have been deleted mid-flight",
                    secret_name,
                )
                raise
            self._core_api.replace_namespaced_secret(
                name=secret_name,
                namespace=self._namespace,
                body=_build_secret(winner_password),
            )
            logger.info(
                "Replaced opencode secret %s (preserved winner password)",
                secret_name,
            )
            return

    def _read_opencode_password(self, sandbox_id: str | UUID) -> str | None:
        """Fetch the cleartext OPENCODE_SERVER_PASSWORD from the per-pod Secret.

        Returns ``None`` if the Secret doesn't exist (e.g. legacy pod
        provisioned before this code landed). Callers should fall back
        to no-auth in that case.
        """
        secret_name = self._get_opencode_secret_name(sandbox_id)
        try:
            secret = self._core_api.read_namespaced_secret(
                name=secret_name, namespace=self._namespace
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        data = secret.data or {}
        raw = data.get(self._OPENCODE_PASSWORD_SECRET_KEY)
        if not raw:
            return None
        return base64.b64decode(raw).decode("utf-8")

    def _delete_opencode_password_secret(self, sandbox_id: str | UUID) -> None:
        """Delete the per-pod opencode-serve auth Secret. Idempotent."""
        secret_name = self._get_opencode_secret_name(sandbox_id)
        try:
            self._core_api.delete_namespaced_secret(
                name=secret_name, namespace=self._namespace
            )
            logger.info("Deleted opencode auth secret %s", secret_name)
        except ApiException as e:
            if e.status not in (404, 410):
                logger.warning(
                    "Failed to delete opencode auth secret %s: %s",
                    secret_name,
                    e,
                )

    def _get_nextjs_url(self, sandbox_id: str, port: int) -> str:
        """Get the internal cluster URL for a session's Next.js server.

        Args:
            sandbox_id: The sandbox ID (string)
            port: The session's allocated Next.js port

        Returns:
            Internal cluster URL for the Next.js server on the specified port
        """
        service_name = self._get_pod_name(sandbox_id)
        return f"http://{service_name}.{self._namespace}.svc.cluster.local:{port}"

    def _load_agent_instructions(
        self,
        skills_section: str,
        connectable_apps_section: str,
        provider: str | None = None,
        model_name: str | None = None,
        nextjs_port: int | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
    ) -> str:
        """Load and populate agent instructions from template file."""
        return generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port,
            disabled_tools=disabled_tools,
            user_name=user_name,
        )

    def _create_sandbox_pod(
        self,
        sandbox_id: str,
        tenant_id: str,
    ) -> client.V1Pod:
        """Build the sandbox Pod from the Helm PodTemplate, overlaying the
        dynamic fields the template can't carry."""
        pod_name = self._get_pod_name(sandbox_id)

        try:
            pod_template = self._core_api.read_namespaced_pod_template(
                name=_PODTEMPLATE_NAME, namespace=self._namespace
            )
        except ApiException as e:
            if e.status == 404:
                raise RuntimeError(
                    f"Sandbox PodTemplate '{_PODTEMPLATE_NAME}' not found in "
                    f"namespace '{self._namespace}'. It must be applied to the "
                    f"cluster (by the deploy tooling when Craft is enabled) "
                    f"before sandboxes can be provisioned."
                ) from e
            raise

        spec: client.V1PodSpec = copy.deepcopy(pod_template.template.spec)
        self._overlay_dynamic_fields(spec, sandbox_id)

        return client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=self._namespace,
                labels={
                    **(pod_template.template.metadata.labels or {}),
                    LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
                    LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
                    LABEL_SANDBOX_ID: sandbox_id,
                    LABEL_TENANT_ID: tenant_id,
                },
            ),
            spec=spec,
        )

    def _overlay_dynamic_fields(self, spec: client.V1PodSpec, sandbox_id: str) -> None:
        """Inject the per-pod values the deploy-time PodTemplate can't carry.

        These are the *only* parts of the pod spec set from Python:
        - hostAliases pinning the proxy ClusterIP (resolved at runtime; the
          firewall blocks DNS so the pod can't resolve it itself)
        - the opencode-auth secretKeyRef env (the Secret name is per-pod)
        - the push public key on the sidecar (derived from the api-server's
          private key, so it's never in the chart; sidecar only)
        """
        spec.host_aliases = [
            client.V1HostAlias(ip=self._resolve_proxy_ip(), hostnames=[_PROXY_ALIAS])
        ]

        secret_name = self._get_opencode_secret_name(sandbox_id)
        sandbox_container = self._require_container(spec, _SANDBOX_CONTAINER_NAME)
        sandbox_container.env = list(sandbox_container.env or []) + [
            client.V1EnvVar(
                name=OPENCODE_SERVER_PASSWORD,
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=secret_name,
                        key=self._OPENCODE_PASSWORD_SECRET_KEY,
                    )
                ),
            ),
            client.V1EnvVar(
                name="OPENCODE_CONFIG_CONTENT",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=secret_name,
                        key=self._OPENCODE_CONFIG_SECRET_KEY,
                    )
                ),
            ),
        ]

        _, push_public_key_b64 = get_push_key_pair()
        sidecar_container = self._require_container(spec, _SIDECAR_CONTAINER_NAME)
        sidecar_container.env = list(sidecar_container.env or []) + [
            client.V1EnvVar(
                name=SIDECAR_PUSH_PUBLIC_KEY_ENV_VAR,
                value=push_public_key_b64,
            ),
        ]

    @staticmethod
    def _require_container(spec: client.V1PodSpec, name: str) -> client.V1Container:
        """Find a container in the PodTemplate by name, or raise a clear error.

        A bare ``next()`` would surface a PodTemplate/version skew (template
        missing the expected container) as an opaque ``StopIteration``; this
        names the container and the fix, matching the 404 PodTemplate error.
        """
        for container in list(spec.containers or []) + list(spec.init_containers or []):
            if container.name == name:
                return container
        raise RuntimeError(
            f"PodTemplate '{_PODTEMPLATE_NAME}' has no '{name}' container. "
            f"The PodTemplate and api-server versions are likely out of sync — "
            f"apply the matching sandbox PodTemplate."
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

        service_name = self._get_pod_name(sandbox_id_str)

        ports = [
            client.V1ServicePort(
                name="opencode",
                port=OPENCODE_SERVE_PORT,
                target_port=OPENCODE_SERVE_PORT,
            ),
            client.V1ServicePort(
                name="push-daemon",
                port=PUSH_DAEMON_PORT,
                target_port=PUSH_DAEMON_PORT,
            ),
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
                    LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
                    LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
                    LABEL_SANDBOX_ID: sandbox_id_str,
                    LABEL_TENANT_ID: tenant_id_str,
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={LABEL_SANDBOX_ID: sandbox_id_str},
                ports=ports,
                publish_not_ready_addresses=True,
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
        service_name = self._get_pod_name(str(sandbox_id))

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

    def stream_pod_logs(
        self,
        sandbox_id: UUID,
        *,
        container: str = _SANDBOX_CONTAINER_NAME,
        tail_lines: int = 200,
    ) -> Iterator[str]:
        """Yield log lines from a sandbox pod's container as they arrive.

        Dev/debug surface — gated by ``ENABLE_OPENCODE_DEBUGGING`` in the
        API layer. Uses ``read_namespaced_pod_log(follow=True)``, which
        returns an iterable of bytes chunks; we decode and split into
        lines ourselves so the consumer sees one log line per yield.
        """
        pod_name = self._get_pod_name(sandbox_id)
        try:
            stream = self._core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self._namespace,
                container=container,
                follow=True,
                tail_lines=tail_lines,
                _preload_content=False,  # required for streaming response
            )
        except ApiException as e:
            logger.warning(
                "stream_pod_logs: read_namespaced_pod_log failed for %s/%s: %s",
                pod_name,
                container,
                e,
            )
            return

        buf = ""
        try:
            for chunk in stream.stream(decode_content=True):
                if not chunk:
                    continue
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    yield line
        finally:
            # No `yield buf` here even if a partial line is in flight —
            # PEP 342 forbids yielding while a generator is closing via
            # GeneratorExit (raises RuntimeError). Losing the last
            # unterminated chunk on client disconnect is acceptable; it
            # would be incomplete anyway.
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

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
        init_statuses = pod.status.init_container_statuses or []
        if not init_statuses:
            return None

        restartable_init_container_names = {
            init_container.name
            for init_container in pod.spec.init_containers or []
            if init_container.name and init_container.restart_policy == "Always"
        }

        for init_status in init_statuses:
            state = init_status.state
            if state is None:
                continue

            waiting = state.waiting
            if waiting and waiting.reason in ["Error", "CrashLoopBackOff"]:
                message = waiting.message or ""
                return (
                    f"Init container '{init_status.name}' is in "
                    f"'{waiting.reason}' state. Message: {message}"
                )

            terminated = state.terminated
            if terminated is None or terminated.exit_code == 0:
                continue
            if init_status.name in restartable_init_container_names:
                continue

            logs = self._get_init_container_logs(pod.metadata.name, init_status.name)
            return (
                f"Init container '{init_status.name}' failed with exit code "
                f"{terminated.exit_code}. Logs:\n{logs}"
            )

        return None

    def _evaluate_pod_readiness(self, pod: client.V1Pod, pod_name: str) -> bool | None:
        """Inspect one pod snapshot for readiness/failure.

        Returns ``True`` if Ready, ``False`` if still progressing, and raises
        ``RuntimeError`` on a terminal failure (init failure, Failed phase,
        Succeeded phase).
        """
        init_error = self._check_init_container_status(pod)
        if init_error:
            raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")

        phase = pod.status.phase
        if phase == "Failed":
            raise RuntimeError(f"Pod {pod_name} failed to start")
        if phase == "Succeeded":
            raise RuntimeError(
                f"Pod {pod_name} completed unexpectedly "
                f"(sandbox pods should run indefinitely)"
            )
        if phase == "Running":
            for condition in pod.status.conditions or []:
                if condition.type == "Ready" and condition.status == "True":
                    return True
        return False

    @staticmethod
    def _sandbox_container_is_ready(pod: client.V1Pod) -> bool:
        """Return True only when the agent container itself is running/ready."""
        for status in pod.status.container_statuses or []:
            if status.name != _SANDBOX_CONTAINER_NAME:
                continue
            state = status.state
            return bool(
                status.ready and state is not None and state.running is not None
            )
        return False

    def _wait_for_pod_ready(
        self,
        pod_name: str,
        timeout: float = POD_READY_TIMEOUT_SECONDS,
    ) -> bool:
        """Block on a single-pod watch until Ready or timeout.

        Watching beats polling: the apiserver pushes status transitions as
        they happen, so we catch ``Ready`` within ~100ms instead of waiting
        for the next poll tick. A bounded retry loop covers ``410 Gone``
        (resource version aged out under us) by re-listing and resuming.
        """
        start_time = time.time()
        field_selector = f"metadata.name={pod_name}"

        try:
            initial = self._core_api.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            if self._evaluate_pod_readiness(initial, pod_name):
                logger.info("Pod %s is ready", pod_name)
                return True
            resource_version = initial.metadata.resource_version
        except ApiException as e:
            if e.status == 404:
                raise RuntimeError(f"Pod {pod_name} was deleted")
            raise

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                break

            w = watch.Watch()
            try:
                stream = w.stream(
                    self._core_api.list_namespaced_pod,
                    namespace=self._namespace,
                    field_selector=field_selector,
                    resource_version=resource_version,
                    timeout_seconds=int(remaining),
                )
                for event in stream:
                    event_type = event.get("type")
                    obj = event.get("object")
                    if event_type == "DELETED":
                        raise RuntimeError(f"Pod {pod_name} was deleted")
                    if not isinstance(obj, client.V1Pod):
                        continue
                    resource_version = obj.metadata.resource_version
                    if self._evaluate_pod_readiness(obj, pod_name):
                        logger.info("Pod %s is ready", pod_name)
                        return True
            except ApiException as e:
                # 410 Gone: resource_version aged out — re-list, check the
                # snapshot for Ready (the pod may have flipped while the
                # watch was expiring), then resume from the list's RV.
                if e.status == 410:
                    listing = self._core_api.list_namespaced_pod(
                        namespace=self._namespace, field_selector=field_selector
                    )
                    for pod in listing.items or []:
                        if self._evaluate_pod_readiness(pod, pod_name):
                            logger.info("Pod %s is ready", pod_name)
                            return True
                    resource_version = listing.metadata.resource_version
                    continue
                raise
            finally:
                w.stop()

        # On timeout, re-check init container status one more time.
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            init_error = self._check_init_container_status(pod)
            if init_error:
                raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")
        except ApiException:
            pass

        logger.warning("Timeout waiting for pod %s to become ready", pod_name)
        return False

    def _wait_for_pod_ip(self, pod_name: str, deadline: float) -> bool:
        """Poll until the pod is assigned an IP, or the monotonic deadline.

        Waits for IP assignment only, never readiness: the init sidecar serves
        the restore endpoint while its startup probe stays blocked, so waiting
        for readiness here would deadlock the restore handshake.
        """
        while time.monotonic() < deadline:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=pod_name, namespace=self._namespace
                )
            except ApiException as e:
                if e.status == 404:
                    raise RuntimeError(f"Pod {pod_name} was deleted")
                raise
            if pod.status.pod_ip:
                logger.info("Pod %s assigned IP %s", pod_name, pod.status.pod_ip)
                return True
            time.sleep(POD_IP_POLL_INTERVAL_SECONDS)

        logger.warning("Timeout waiting for pod %s to be assigned an IP", pod_name)
        return False

    def _pod_exists_and_healthy(self, pod_name: str) -> bool:
        """Check if a pod exists and the sandbox app container is ready.

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
                    if (
                        condition.type == "Ready"
                        and condition.status == "True"
                        and self._sandbox_container_is_ready(pod)
                    ):
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
        llm_config: LLMProviderConfig,
        onyx_pat: str | None = None,
        *,
        all_llm_configs: list[LLMProviderConfig] | None = None,
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
            onyx_pat: Required by the interface and the Docker backend; on K8s
                the pod ships a placeholder and the proxy injects the real PAT,
                so this is only checked as a provisioning precondition.

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

        if not onyx_pat:
            raise ValueError("onyx_pat is required for Kubernetes sandbox provisioning")
        if not SANDBOX_API_SERVER_URL:
            raise ValueError(
                "SANDBOX_API_SERVER_URL must be set for Kubernetes sandbox provisioning"
            )
        if not SANDBOX_PROXY_HOST:
            raise ValueError(
                "SANDBOX_PROXY_HOST must be set for Kubernetes sandbox provisioning"
            )

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

            # Reusing a live pod: clear any stale tombstone so event-bus
            # creation can attach. A stale password heals via the 401 path in
            # the readiness probe below.
            with self._event_buses_lock:
                self._terminated_sandboxes.discard(sandbox_id)

            if not self._wait_for_opencode_serve_ready(sandbox_id):
                raise RuntimeError(
                    f"opencode-serve never became ready in existing sandbox pod {pod_name}"
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

        created_pod = False

        try:
            # Re-provision: clear tombstone + cached info so subscribes
            # build a fresh bus with the new Secret's password.
            with self._event_buses_lock:
                self._terminated_sandboxes.discard(sandbox_id)
            self._invalidate_serve_connection_info(sandbox_id)

            # Secret must exist before the Pod (secretKeyRef). Pre-load every
            # provider for cross-provider model overrides; keys are swapped for
            # the proxy placeholder so the pod never holds them.
            providers = _placeholder_llm_configs(all_llm_configs or [llm_config])
            opencode_config_json = json.dumps(
                build_multi_provider_opencode_config(
                    providers=providers,
                    default_provider=llm_config.provider,
                    default_model=llm_config.model_name,
                    disabled_tools=OPENCODE_DISABLED_TOOLS,
                    plugins=[
                        _OPENCODE_CONNECT_APP_PLUGIN_PATH,
                        _OPENCODE_SESSION_TAG_PLUGIN_PATH,
                    ],
                )
            )
            self._provision_opencode_secret(str(sandbox_id), opencode_config_json)

            # 1. Create Pod (user-level only, no session setup)
            logger.debug("Creating Pod %s", pod_name)
            startup_restore_required = True
            pod = self._create_sandbox_pod(
                sandbox_id=str(sandbox_id),
                tenant_id=tenant_id,
            )
            try:
                self._core_api.create_namespaced_pod(
                    namespace=self._namespace,
                    body=pod,
                )
                created_pod = True
            except ApiException as e:
                if e.status == 409:
                    logger.warning(
                        "Pod %s already exists (409 conflict, this shouldn't normally happen), checking if it's healthy...",
                        pod_name,
                    )
                    if self._pod_exists_and_healthy(pod_name):
                        # Another provisioner completed startup restore while this
                        # request was creating the pod. Reuse the live pod instead
                        # of sending a redundant restore request.
                        logger.warning(
                            "During provisioning, discovered that pod %s already exists. Reusing",
                            pod_name,
                        )
                        startup_restore_required = False
                    else:
                        logger.warning(
                            "Pod %s exists but is not ready; running startup restore "
                            "handshake without cleanup ownership",
                            pod_name,
                        )
                else:
                    raise

            # 2. Create Service (handles terminating services)
            self._ensure_service_exists(sandbox_id, tenant_id)

            # 3. Restore opencode history before the sandbox app container starts;
            # the init sidecar serves the restore endpoint while its startup probe
            # stays blocked, so opencode-serve can't open an empty DB first. The IP
            # wait and the restore draw from one deadline so slow scheduling leaves
            # less budget for the restore rather than stacking two full timeouts.
            if startup_restore_required:
                restore_deadline = (
                    time.monotonic() + OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS
                )
                if not self._wait_for_pod_ip(pod_name, restore_deadline):
                    raise RuntimeError(
                        f"Timeout waiting for sandbox pod {pod_name} to be assigned an IP"
                    )
                self.restore_opencode_history_snapshot(
                    sandbox_id,
                    tenant_id,
                    timeout_seconds=restore_deadline - time.monotonic(),
                )

            # 4. Wait for pod to be ready
            logger.info("Waiting for pod %s to become ready...", pod_name)
            if not self._wait_for_pod_ready(pod_name):
                raise RuntimeError(
                    f"Timeout waiting for sandbox pod {pod_name} to become ready"
                )

            # 5. Wait for opencode-serve to bind :4096 .
            if not self._wait_for_opencode_serve_ready(sandbox_id):
                raise RuntimeError(
                    f"opencode-serve never became ready in sandbox pod {pod_name}"
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
            # Only clean up resources created by this provision call. If a
            # concurrent provisioner finished successfully, leave the live pod alone.
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
                if created_pod:
                    self._cleanup_kubernetes_resources(str(sandbox_id))
                else:
                    logger.warning(
                        "Not cleaning up sandbox %s after provisioning failure "
                        "because this provisioner did not create the pod",
                        sandbox_id,
                    )
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
        service_name = self._get_pod_name(sandbox_id)

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

        # Delete the per-pod opencode-serve auth Secret. Idempotent.
        # Done after the Pod is being torn down so no live container is
        # still trying to resolve the secretKeyRef.
        self._delete_opencode_password_secret(sandbox_id)

        # Wait for resources to be fully deleted to prevent 409 conflicts
        # on immediate re-provisioning
        if wait_for_deletion:
            if service_deleted:
                self._wait_for_resource_deletion("service", service_name)
            if pod_deleted:
                self._wait_for_resource_deletion("pod", pod_name)

    def terminate(self, sandbox_id: UUID) -> None:
        """Tear down event buses, then delete Service + Pod."""
        self._close_all_sandbox_buses(sandbox_id)
        self._cleanup_kubernetes_resources(str(sandbox_id))
        logger.info("Terminated Kubernetes sandbox %s", sandbox_id)

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        connectable_apps_section: str,
        user_name: str | None = None,
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
            user_name: User's name for personalization in AGENTS.md

        Raises:
            RuntimeError: If workspace setup fails
        """
        pod_name = self._get_pod_name(str(sandbox_id))
        session_path = f"/workspace/sessions/{session_id}"

        # Paths inside the pod (created during workspace setup below):
        # - {session_path}/attachments: user-uploaded files
        #
        # Attachments section is injected dynamically when first file is uploaded.
        agent_instructions = self._load_agent_instructions(
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
        )

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
                container=_SANDBOX_CONTAINER_NAME,
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
    ) -> None:
        """Clean up a session workspace (on session delete). Executes
        kubectl exec to remove the session directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
        """
        self._close_session_buses(sandbox_id, session_id)

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
                container=_SANDBOX_CONTAINER_NAME,
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
        """Create a FileStore-backed snapshot via the sidecar filesystem API.

        Captures:
        - sessions/$session_id/outputs/
        - sessions/$session_id/attachments/

        Returns None if there are no outputs to snapshot.
        """
        body = SnapshotCreateRequest(session_id=session_id).model_dump_json().encode()

        with self._sidecar_client.request_and_stream_new_snapshot(
            sandbox_id=sandbox_id,
            endpoint_path=SIDECAR_SNAPSHOT_CREATE_PATH,
            body=body,
            content_type="application/json",
            operation_label="Snapshot create",
            timeout_seconds=300.0,
        ) as snapshot_stream:
            if snapshot_stream is None:
                logger.info("No outputs to snapshot for session %s", session_id)
                return None

            _, storage_path, size_bytes = (
                self._snapshot_manager.persist_snapshot_from_stream(
                    stream=snapshot_stream,
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )

        logger.info(
            "Created snapshot for sandbox %s session %s (size=%s bytes).",
            sandbox_id,
            session_id,
            size_bytes,
        )
        return SnapshotResult(
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

    def create_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = 300.0,
    ) -> bool:
        with self._sidecar_client.request_and_stream_new_snapshot(
            sandbox_id=sandbox_id,
            endpoint_path=SIDECAR_OPENCODE_HISTORY_CREATE_PATH,
            body=b"",
            content_type="application/octet-stream",
            operation_label="opencode history snapshot",
            timeout_seconds=timeout_seconds,
        ) as snapshot_stream:
            if snapshot_stream is None:
                logger.info(
                    "No opencode history to snapshot for sandbox %s", sandbox_id
                )
                return False

            storage_path, size_bytes = (
                self._snapshot_manager.persist_opencode_snapshot_from_stream(
                    stream=snapshot_stream,
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )

        logger.info(
            "Created opencode history snapshot for sandbox %s (path=%s size=%s bytes)",
            sandbox_id,
            storage_path,
            size_bytes,
        )
        return True

    def restore_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS,
    ) -> bool:
        if not self._snapshot_manager.has_opencode_history_snapshot(
            tenant_id, str(sandbox_id)
        ):
            logger.info("No opencode history snapshot found for sandbox %s", sandbox_id)
            self._mark_opencode_history_restored(
                sandbox_id=sandbox_id,
                timeout_seconds=timeout_seconds,
            )
            return False

        try:
            with tempfile.NamedTemporaryFile(mode="w+b", suffix=".tar.gz") as tmp_file:
                storage_path = SnapshotManager.opencode_history_storage_path(
                    tenant_id, str(sandbox_id)
                )
                self._snapshot_manager.restore_snapshot_to_stream(
                    storage_path,
                    tmp_file,
                )
                tmp_file.flush()
                tmp_file.file.seek(0)
                sha256_hex = hashlib.file_digest(
                    cast(io.BufferedRandom, tmp_file.file), "sha256"
                ).hexdigest()
                tmp_file.file.seek(0)
                self._sidecar_client.post_archive(
                    sandbox_id=sandbox_id,
                    endpoint_path=SIDECAR_OPENCODE_HISTORY_RESTORE_PATH,
                    archive_file=tmp_file,
                    sha256_hex=sha256_hex,
                    operation_label="opencode history restore",
                    timeout_seconds=timeout_seconds,
                )
            logger.info("Restored opencode history snapshot for sandbox %s", sandbox_id)
            return True
        except Exception as e:
            raise RuntimeError(
                f"Failed to restore opencode history snapshot: {e}"
            ) from e

    def _mark_opencode_history_restored(
        self,
        *,
        sandbox_id: UUID,
        timeout_seconds: float = OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS,
    ) -> None:
        self._sidecar_client.post_empty(
            sandbox_id=sandbox_id,
            endpoint_path=SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH,
            operation_label="opencode history restore marker",
            timeout_seconds=timeout_seconds,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
        connectable_apps_section: str,
    ) -> None:
        """Restore a FileStore-backed snapshot through the sidecar filesystem API.

        Steps:
        1. Read the snapshot from Onyx FileStore in the api-server
        2. Stream it to the sidecar, which extracts it in the session workspace
        3. Regenerate configuration files (AGENTS.md, opencode.json)
        4. Start the NextJS dev server (skipped when ``nextjs_port`` is None,
           e.g. for headless scheduled-task fires that don't attach a preview).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: FileStore file id for the snapshot archive
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
            with tempfile.NamedTemporaryFile(mode="w+b", suffix=".tar.gz") as tmp_file:
                self._snapshot_manager.restore_snapshot_to_stream(
                    snapshot_storage_path, tmp_file
                )
                tmp_file.flush()
                tmp_file.file.seek(0)
                sha256_hex = hashlib.file_digest(
                    cast(io.BufferedRandom, tmp_file.file), "sha256"
                ).hexdigest()
                tmp_file.file.seek(0)
                self._sidecar_client.post_archive(
                    sandbox_id=sandbox_id,
                    endpoint_path=sidecar_snapshot_restore_path(session_id),
                    archive_file=tmp_file,
                    sha256_hex=sha256_hex,
                    operation_label="Snapshot restore",
                )

            # Regenerate configuration files that aren't in the snapshot.
            self._regenerate_session_config(
                pod_name=pod_name,
                session_path=safe_session_path,
                llm_config=llm_config,
                nextjs_port=nextjs_port,
                skills_section=skills_section,
                connectable_apps_section=connectable_apps_section,
            )

            if nextjs_port is not None:
                start_script = _build_nextjs_start_script(
                    safe_session_path, nextjs_port, check_node_modules=True
                )
                k8s_stream(
                    self._stream_core_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self._namespace,
                    container=_SANDBOX_CONTAINER_NAME,
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
        connectable_apps_section: str,
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
            connectable_apps_section=connectable_apps_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=None,
        )

        agent_instructions_escaped = agent_instructions.replace("'", "'\\''")
        config_script = f"""
set -e
mkdir -p {session_path}/.opencode
ln -sfn /workspace/managed/skills {session_path}/.opencode/skills
ln -sfn /workspace/managed/user_library {session_path}/user_library
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md
"""

        logger.info("Regenerating session configuration files")
        k8s_stream(
            self._stream_core_api.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=self._namespace,
            container=_SANDBOX_CONTAINER_NAME,
            command=["/bin/sh", "-c", config_script],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        logger.info("Session configuration files regenerated")

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check whether the agent container and sidecar are both healthy."""
        pod_name = self._get_pod_name(str(sandbox_id))
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
        except ApiException as e:
            if e.status == 404:
                return False
            raise
        if not self._sandbox_container_is_ready(pod):
            return False

        return self._sidecar_client.is_healthy(
            sandbox_id=sandbox_id,
            timeout_seconds=timeout,
        )

    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        """Build serve connection info from the per-pod Secret. URL uses
        the Service DNS (not pod IP) so telepresence dev paths work."""
        service_name = self._get_pod_name(str(sandbox_id))
        return ServeConnectionInfo(
            base_url=(
                f"http://{service_name}.{self._namespace}.svc.cluster.local"
                f":{OPENCODE_SERVE_PORT}"
            ),
            password=self._read_opencode_password(sandbox_id),
        )

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the session workspace.

        For Kubernetes backend, the sandbox sidecar owns pod-local filesystem
        access and returns structured entries.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        try:
            return self._sidecar_client.list_directory(
                sandbox_id=sandbox_id,
                session_id=session_id,
                path=path,
            )
        except SidecarStatusError as e:
            try:
                detail = json.loads(e.body).get("detail", "")
            except (TypeError, ValueError):
                detail = ""

            if e.status_code == 400 and detail == "path traversal is not allowed":
                raise ValueError(f"path traversal attempted: {path}") from e
            if e.status_code == 404 and detail == "path not found or not a directory":
                raise ValueError(f"Path not found or not a directory: {path}") from e
            raise RuntimeError(f"Failed to list directory: {e}") from e
        except SidecarRequestError as e:
            raise RuntimeError(f"Failed to list directory: {e}") from e

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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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
                container=_SANDBOX_CONTAINER_NAME,
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

    def _resolve_proxy_ip(self) -> str:
        """Resolve SANDBOX_PROXY_HOST to a pod-routable IP for the egress
        hostAlias. Reads the Service ClusterIP from the k8s API, not the
        api-server's OS resolver, so it stays correct under telepresence (whose
        resolver returns a synthetic, pod-unroutable IP). A numeric host (CI
        passes the ClusterIP directly) is returned unchanged."""
        host = SANDBOX_PROXY_HOST
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        name, _, rest = host.partition(".")
        namespace = rest.partition(".")[0] or SANDBOX_PROXY_NAMESPACE
        last_err: Exception | None = None
        for attempt in range(_PROXY_RESOLVE_RETRY_ATTEMPTS):
            try:
                cluster_ip = self._core_api.read_namespaced_service(
                    name=name, namespace=namespace
                ).spec.cluster_ip
                if cluster_ip and cluster_ip != "None":
                    return cluster_ip
                last_err = RuntimeError(f"Service {name} has no ClusterIP")
            except ApiException as e:
                last_err = e
            if attempt < _PROXY_RESOLVE_RETRY_ATTEMPTS - 1:
                time.sleep(_PROXY_RESOLVE_RETRY_BACKOFF_S * (2**attempt))
        raise RuntimeError(
            f"failed to resolve proxy ClusterIP for SANDBOX_PROXY_HOST={host!r} "
            f"after {_PROXY_RESOLVE_RETRY_ATTEMPTS} attempts: {last_err}"
        )

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        """Build tar.gz, POST to the in-pod daemon."""
        pod_name = self._get_pod_name(sandbox_id)
        tar_bytes, sha256_hex = _build_targz(files)

        try:
            self._sidecar_client.push_archive(
                sandbox_id=sandbox_id,
                mount_path=mount_path,
                archive=tar_bytes,
                sha256_hex=sha256_hex,
                operation_label=pod_name,
                timeout_seconds=30.0,
            )
        except SidecarRequestError as e:
            raise RetriableWriteError(f"Push to {pod_name} failed: {e}") from e
        except SidecarStatusError as e:
            err = f"{pod_name}: {e.status_code} {e.body}"
            if e.status_code >= 500:
                raise RetriableWriteError(err) from e
            raise FatalWriteError(err) from e
