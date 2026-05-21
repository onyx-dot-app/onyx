"""Docker-based sandbox manager for self-hosted docker-compose deployments.

This is the docker-compose analogue of
:class:`KubernetesSandboxManager`. The api_server mounts the Docker socket
and drives container lifecycle (provision/terminate, exec into the sandbox
for setup, file ops, and ACP messaging) the same way the K8s manager drives
the Kubernetes API.

User-shared sandbox model
-------------------------
One container per user, multiple sessions under ``/workspace/sessions``,
matching the K8s pod model. ``provision()`` creates a single container
and a per-sandbox named volume mounted at ``/workspace/sessions``.

Snapshots
---------
Docker V1 streams tar bytes through api_server-owned ``FileStore`` rather
than handing storage credentials to the agent container. ``create_snapshot``
runs ``tar`` inside the sandbox via docker exec, pipes the bytes through
``SnapshotManager.create_snapshot_from_stream``; ``restore_snapshot`` runs
the reverse path via ``stream_stdin_to_container``.

Security model
--------------
Sandbox containers run with:

- ``--security-opt no-new-privileges``
- ``--cap-drop ALL``
- ``user=1000:1000``
- no Docker socket mount
- no S3 / MinIO / Postgres / Redis / FileStore credentials in env
- a fixed env allowlist (``ONYX_PAT`` + ``ONYX_SERVER_URL`` only)
- only the dedicated sandbox bridge network — never compose's default
  network. As a result api_server / postgres / redis / minio /
  model_server are NOT reachable by service name from inside the sandbox.

Outbound communication is intentionally limited to:

1. Public internet over HTTPS (the bridge has default internet egress;
   block at the host's ``DOCKER-USER`` chain if you need a stricter
   posture, e.g. for EC2 IMDS).
2. The Onyx API via ``ONYX_SERVER_URL`` — which must be the *public*
   HTTPS URL the agent reaches just like any other onyx-cli client.

All control-plane traffic from api_server → sandbox uses the Docker
Engine API (``docker exec``), never network sockets to the sandbox.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import mimetypes
import re
import shlex
import tarfile
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import ATTACHMENTS_DIRECTORY
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_API_SERVER_URL
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_DOCKER_CPU_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_MEMORY_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_NETWORK
from onyx.server.features.build.configs import SANDBOX_DOCKER_SOCKET
from onyx.server.features.build.configs import SANDBOX_DOCKER_VOLUME_PREFIX
from onyx.server.features.build.sandbox.acp.base import ACPEvent
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR
from onyx.server.features.build.sandbox.base import BUN_IMAGE_CACHE_DIR
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker.internal.acp_exec_client import (
    DockerACPExecClient,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import ExecError
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    run_in_container,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    stream_stdin_to_container,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    stream_stdout_from_container,
)
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
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


# Labels used to find sandbox containers/volumes/networks. Match the K8s
# label keys where reasonable so dashboards/queries don't drift.
LABEL_COMPONENT = "onyx.app/component"
LABEL_COMPONENT_VALUE = "craft-sandbox"
LABEL_SANDBOX_ID = "onyx.app/sandbox-id"
LABEL_TENANT_ID = "onyx.app/tenant-id"
LABEL_USER_ID = "onyx.app/user-id"

# Path conventions inside the sandbox container — must match the K8s image.
WORKSPACE_ROOT = "/workspace"
SESSIONS_ROOT = f"{WORKSPACE_ROOT}/sessions"
TEMPLATES_OUTPUTS_PATH = f"{WORKSPACE_ROOT}/templates/outputs"
MANAGED_SKILLS_PATH = f"{WORKSPACE_ROOT}/managed/skills"

# Mirror the K8s constants in ``kubernetes_sandbox_manager`` (POD_READY_*),
# which are also module-level and not env-tunable.
CONTAINER_READY_TIMEOUT_SECONDS = 120
CONTAINER_READY_POLL_INTERVAL_SECONDS = 1.0


def _build_nextjs_start_script(
    session_path: str,
    nextjs_port: int,
    check_node_modules: bool = False,
) -> str:
    """Shell script to spawn Next.js in the background and record its PID."""
    install_check = ""
    if check_node_modules:
        install_check = f"""
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies with bun..."
    BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \
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


def _sandbox_container_name(sandbox_id: str | UUID) -> str:
    """Container name derived from sandbox ID. Matches K8s ``sandbox-<id8>``."""
    return f"sandbox-{str(sandbox_id)[:8]}"


def _sandbox_volume_name(sandbox_id: str | UUID) -> str:
    """Per-sandbox named volume holding ``/workspace/sessions``."""
    return f"{SANDBOX_DOCKER_VOLUME_PREFIX}{str(sandbox_id)[:8]}"


def _sanitize_relative_path(path: str) -> str:
    """Strip ``..`` components and leading ``/`` from a user-provided path."""
    path_obj = Path(path.lstrip("/"))
    clean_parts = [p for p in path_obj.parts if p != ".."]
    return str(Path(*clean_parts)) if clean_parts else "."


def _validate_strict_path(path: str) -> None:
    """Reject paths with traversal, URL escapes, null bytes, or shell metacharacters."""
    if ".." in path or "%" in path or "\x00" in path:
        raise ValueError("Invalid path: potential path traversal detected")
    if re.search(r'[;&|`$(){}[\]<>\'"\n\r\\]', path):
        raise ValueError("Invalid path: contains disallowed characters")
    if not re.match(r"^[a-zA-Z0-9_\-./]+$", path.lstrip("/")):
        raise ValueError("Invalid path: contains disallowed characters")


_COMPOSE_INTERNAL_HOSTNAMES = {
    "api_server",
    "background",
    "relational_db",
    "cache",
    "minio",
    "model_server",
    "indexing_model_server",
    "inference_model_server",
    "web_server",
    "vespa",
}


def _looks_like_internal_compose_host(url: str) -> bool:
    """Heuristic: does ``url`` reference a compose-internal service hostname?

    Used to warn deployers that pointed SANDBOX_API_SERVER_URL at the
    api_server's compose DNS name. Sandboxes can't resolve that — they
    only join the craft bridge network — so the URL must be the public
    Onyx URL.
    """
    if not url:
        return False
    lowered = url.lower()
    for host in _COMPOSE_INTERNAL_HOSTNAMES:
        if (
            f"//{host}:" in lowered
            or f"//{host}/" in lowered
            or lowered.endswith(f"//{host}")
        ):
            return True
    return False


def _detect_compose_project(docker_client: DockerClient) -> str | None:
    """Best-effort lookup of the calling container's compose project name.

    We inspect the container we're currently running in (matched by hostname,
    which Docker sets to the container short-ID) and pull
    ``com.docker.compose.project`` off its labels. Returns None when running
    outside compose (e.g. local tests) so the manager falls back to
    "ungrouped" sandbox containers.
    """
    import socket as _socket

    try:
        own = docker_client.containers.get(_socket.gethostname())
    except (NotFound, APIError) as e:
        logger.debug("compose project auto-detect skipped: %s", e)
        return None
    return (own.labels or {}).get("com.docker.compose.project")


def build_sandbox_labels(
    sandbox_id: UUID,
    tenant_id: str,
    user_id: UUID | None,
    compose_project: str | None = None,
) -> dict[str, str]:
    """Standard label set for sandbox-owned docker resources.

    ``compose_project`` is added as ``com.docker.compose.project`` so
    Docker Desktop groups sandbox containers under the same "onyx" stack
    header as api_server/postgres/redis/etc. Auto-detected by
    ``DockerSandboxManager`` from its own container's labels.
    """
    labels: dict[str, str] = {
        LABEL_COMPONENT: LABEL_COMPONENT_VALUE,
        LABEL_SANDBOX_ID: str(sandbox_id),
        LABEL_TENANT_ID: tenant_id,
        "app.kubernetes.io/managed-by": "onyx",
    }
    if user_id is not None:
        labels[LABEL_USER_ID] = str(user_id)
    if compose_project:
        labels["com.docker.compose.project"] = compose_project
    return labels


class ContainerCreateKwargs(TypedDict):
    """Kwargs we pass to ``DockerClient.containers.run``.

    Typed so ``test_docker_manager_config.py`` can read specific fields
    without ``cast``.
    """

    name: str
    image: str
    command: list[str]
    detach: bool
    labels: dict[str, str]
    user: str
    cap_drop: list[str]
    security_opt: list[str]
    privileged: bool
    read_only: bool
    network: str
    environment: dict[str, str]
    volumes: dict[str, dict[str, str]]
    mem_limit: str
    nano_cpus: int
    restart_policy: dict[str, str]


def build_container_create_kwargs(
    *,
    sandbox_id: UUID,
    user_id: UUID,
    tenant_id: str,
    image: str,
    onyx_pat: str,
    api_server_url: str,
    network: str,
    volume_name: str,
    memory_limit: str,
    cpu_limit: float,
    compose_project: str | None = None,
) -> ContainerCreateKwargs:
    """Build the kwargs dict for ``DockerClient.containers.create``.

    Sandbox isolation invariants enforced here (locked down by
    ``test_docker_manager_config.py``):

    - **Env is a fixed allowlist**: ONYX_PAT + ONYX_SERVER_URL only. No
      caller can inject arbitrary env. No S3/MinIO/Postgres/Redis
      credentials. No compose service hostnames.
    - **No host mounts**: only the per-sandbox named volume mounted at
      ``/workspace/sessions``. No Docker socket. No FileStore root.
    - **Cap-dropped non-root**: ``user=1000:1000``, ``cap_drop=ALL``,
      ``security_opt=no-new-privileges``, ``privileged=False``.
    - **Single network**: joins only the caller-supplied ``network`` (the
      dedicated ``onyx_craft_sandbox`` bridge). Does NOT join compose's
      default network; api_server / postgres / redis / minio are
      unreachable by service name.

    ``ONYX_SERVER_URL`` must be the *public* Onyx URL (the one onyx-cli
    inside the sandbox will hit over HTTPS) — not an internal compose DNS
    name. We emit a warning if it looks like the latter, since reaching it
    would require the sandbox to be on the compose default network.
    """
    if _looks_like_internal_compose_host(api_server_url):
        logger.warning(
            "SANDBOX_API_SERVER_URL=%s looks like an internal compose hostname. "
            "Sandboxes only join the craft bridge network and reach the API "
            "server like any other public client, so this URL must resolve "
            "publicly (e.g. https://onyx.your-org.com). Internal DNS will "
            "fail and the agent will see 'connection refused'.",
            api_server_url,
        )

    env = {
        "ONYX_PAT": onyx_pat,
        "ONYX_SERVER_URL": api_server_url,
    }

    security_opts = ["no-new-privileges:true"]

    return ContainerCreateKwargs(
        name=_sandbox_container_name(sandbox_id),
        image=image,
        command=["/workspace/entrypoint.sh"],
        detach=True,
        labels=build_sandbox_labels(
            sandbox_id, tenant_id, user_id, compose_project=compose_project
        ),
        user="1000:1000",
        cap_drop=["ALL"],
        security_opt=security_opts,
        privileged=False,
        read_only=False,
        network=network,
        environment=env,
        volumes={
            volume_name: {"bind": SESSIONS_ROOT, "mode": "rw"},
        },
        mem_limit=memory_limit,
        nano_cpus=int(cpu_limit * 1_000_000_000),
        restart_policy={"Name": "unless-stopped"},
        # No docker socket mount. No S3/MinIO env. No FileStore credentials.
    )


class DockerSandboxManager(SandboxManager):
    """Sandbox manager that drives the host Docker Engine.

    Singleton; use :func:`get_sandbox_manager` to obtain the instance.
    """

    _instance: "DockerSandboxManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "DockerSandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        self._docker = DockerClient(base_url=f"unix://{SANDBOX_DOCKER_SOCKET}")
        self._image = SANDBOX_CONTAINER_IMAGE
        self._network_name = SANDBOX_DOCKER_NETWORK
        self._memory_limit = SANDBOX_DOCKER_MEMORY_LIMIT
        self._cpu_limit = SANDBOX_DOCKER_CPU_LIMIT
        self._snapshot_manager = SnapshotManager(get_default_file_store())

        build_dir = Path(__file__).parent.parent.parent
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"

        # Auto-detect compose project so Docker Desktop groups sandbox
        # containers under the same stack header as api_server. When
        # api_server runs inside compose, its own container has the
        # ``com.docker.compose.project`` label; we copy that value onto
        # every sandbox we create. When api_server runs outside compose
        # (e.g. unit tests) this resolves to None and no label is added.
        self._compose_project = _detect_compose_project(self._docker)

        logger.info(
            "DockerSandboxManager initialized: socket=%s image=%s network=%s "
            "compose_project=%s",
            SANDBOX_DOCKER_SOCKET,
            self._image,
            self._network_name,
            self._compose_project,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_sandbox_network(self) -> None:
        try:
            self._docker.networks.get(self._network_name)
            return
        except NotFound:
            pass
        logger.info("Creating sandbox network: %s", self._network_name)
        # ``onyx_craft_sandbox`` is intentionally a plain bridge with
        # internal=False so the agent can reach the public internet.
        # Host-level firewall rules (DOCKER-USER chain) block IMDS at the
        # network layer; app-level blocking is best-effort only.
        self._docker.networks.create(
            self._network_name,
            driver="bridge",
            labels={
                LABEL_COMPONENT: LABEL_COMPONENT_VALUE,
                "app.kubernetes.io/managed-by": "onyx",
            },
        )

    def _ensure_sandbox_volume(self, sandbox_id: UUID, tenant_id: str) -> str:
        volume_name = _sandbox_volume_name(sandbox_id)
        try:
            self._docker.volumes.get(volume_name)
            return volume_name
        except NotFound:
            pass
        logger.info("Creating sandbox volume: %s", volume_name)
        self._docker.volumes.create(
            name=volume_name,
            labels=build_sandbox_labels(
                sandbox_id, tenant_id, None, compose_project=self._compose_project
            ),
        )
        return volume_name

    def _get_container(self, sandbox_id: UUID) -> Container | None:
        try:
            return self._docker.containers.get(_sandbox_container_name(sandbox_id))
        except NotFound:
            return None

    def _require_container(self, sandbox_id: UUID) -> Container:
        c = self._get_container(sandbox_id)
        if c is None:
            raise RuntimeError(
                f"Sandbox {sandbox_id} container not found — call provision() first"
            )
        return c

    def _wait_for_container_running(self, container: Container) -> bool:
        start_time = time.time()
        while time.time() - start_time < CONTAINER_READY_TIMEOUT_SECONDS:
            container.reload()
            state = (container.attrs or {}).get("State") or {}
            status = state.get("Status")
            if status == "running":
                return True
            if status in ("exited", "dead"):
                logs = container.logs(tail=100).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Sandbox container {container.name} exited unexpectedly. "
                    f"Logs:\n{logs[:2000]}"
                )
            time.sleep(CONTAINER_READY_POLL_INTERVAL_SECONDS)
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,  # noqa: ARG002
        onyx_pat: str | None = None,
    ) -> SandboxInfo:
        if not onyx_pat:
            raise ValueError("onyx_pat is required for Docker sandbox provisioning")
        if not SANDBOX_API_SERVER_URL:
            raise ValueError(
                "SANDBOX_API_SERVER_URL must be set for Docker sandbox provisioning"
            )

        logger.info(
            "Provisioning Docker sandbox %s for user %s, tenant %s",
            sandbox_id,
            user_id,
            tenant_id,
        )

        # 1. Idempotency: reuse an existing container if at all possible.
        container = self._reuse_existing_container(sandbox_id)
        if container is None:
            # 2. Otherwise create a fresh one.
            self._ensure_sandbox_network()
            volume_name = self._ensure_sandbox_volume(sandbox_id, tenant_id)
            container = self._create_sandbox_container(
                sandbox_id=sandbox_id,
                user_id=user_id,
                tenant_id=tenant_id,
                onyx_pat=onyx_pat,
                volume_name=volume_name,
            )

        if not self._wait_for_container_running(container):
            raise RuntimeError(
                f"Timeout waiting for sandbox container {container.name} to be running"
            )

        logger.info(
            "Provisioned Docker sandbox %s, container=%s", sandbox_id, container.name
        )
        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=f"docker://{container.name}",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def _reuse_existing_container(self, sandbox_id: UUID) -> Container | None:
        """Return a running/restarted container if one exists, else None."""
        existing = self._get_container(sandbox_id)
        if existing is None:
            return None
        existing.reload()
        status = ((existing.attrs or {}).get("State") or {}).get("Status")
        if status == "running":
            logger.info("Reusing existing running sandbox %s", sandbox_id)
            return existing
        if status in ("exited", "created"):
            logger.info("Starting existing stopped sandbox %s", existing.name)
            existing.start()
            return existing
        return None

    def _create_sandbox_container(
        self,
        *,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str,
        volume_name: str,
    ) -> Container:
        """Run docker create + start with our security/network/labels invariants."""
        create_kwargs = build_container_create_kwargs(
            sandbox_id=sandbox_id,
            user_id=user_id,
            tenant_id=tenant_id,
            image=self._image,
            onyx_pat=onyx_pat,
            api_server_url=SANDBOX_API_SERVER_URL,
            network=self._network_name,
            volume_name=volume_name,
            memory_limit=self._memory_limit,
            cpu_limit=self._cpu_limit,
            compose_project=self._compose_project,
        )
        try:
            # ty can't statically verify TypedDict-unpack against ``run``'s
            # 50+ named-parameter overloads; types are pinned by
            # ``ContainerCreateKwargs`` at construction time.
            return self._docker.containers.run(**create_kwargs)  # ty: ignore[no-matching-overload]
        except APIError as e:
            # 409 means a concurrent request created the same container.
            if "Conflict" in str(e) or getattr(e, "status_code", None) == 409:
                logger.info("Sandbox container %s already exists, reusing", sandbox_id)
                return self._require_container(sandbox_id)
            raise RuntimeError(f"Failed to create sandbox container: {e}") from e

    def terminate(self, sandbox_id: UUID) -> None:
        container = self._get_container(sandbox_id)
        if container is not None:
            try:
                container.remove(force=True, v=False)
                logger.info("Removed sandbox container %s", container.name)
            except (APIError, NotFound) as e:
                logger.warning(
                    "Error removing sandbox container %s: %s", container.name, e
                )

        # Remove the per-sandbox named volume separately so terminate is safe
        # to call when the container was already gone.
        volume_name = _sandbox_volume_name(sandbox_id)
        try:
            volume = self._docker.volumes.get(volume_name)
            volume.remove(force=True)
            logger.info("Removed sandbox volume %s", volume_name)
        except NotFound:
            pass
        except APIError as e:
            logger.warning("Error removing sandbox volume %s: %s", volume_name, e)

        logger.info("Terminated Docker sandbox %s", sandbox_id)

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:  # noqa: ARG002
        container = self._get_container(sandbox_id)
        if container is None:
            return False
        try:
            container.reload()
        except (APIError, NotFound):
            return False
        state = (container.attrs or {}).get("State") or {}
        return state.get("Status") == "running"

    # ------------------------------------------------------------------
    # Session workspace setup
    # ------------------------------------------------------------------

    def _render_session_files(
        self,
        *,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> tuple[str, str]:
        """Render shell-escaped (AGENTS.md, opencode.json) for a session.

        Shared between fresh setup and post-restore regeneration since
        neither AGENTS.md nor opencode.json is included in snapshots.
        """
        agent_instructions = generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_section=skills_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
            user_role=user_role,
        )
        opencode_json = json.dumps(
            build_opencode_config(
                provider=llm_config.provider,
                model_name=llm_config.model_name,
                api_key=llm_config.api_key or None,
                api_base=llm_config.api_base,
                disabled_tools=OPENCODE_DISABLED_TOOLS,
            )
        )
        # Escape single quotes for ``printf '%s' '...'``.
        return (
            agent_instructions.replace("'", "'\\''"),
            opencode_json.replace("'", "'\\''"),
        )

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
        if snapshot_path:
            logger.warning(
                "setup_session_workspace called with snapshot_path=%s; use "
                "restore_snapshot for snapshot restores. Session %s will be "
                "set up with the fresh template instead.",
                snapshot_path,
                session_id,
            )

        container = self._require_container(sandbox_id)
        session_path = f"{SESSIONS_ROOT}/{session_id}"
        agents_md, opencode_json = self._render_session_files(
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            user_name=user_name,
            user_role=user_role,
        )

        nextjs_start = (
            _build_nextjs_start_script(session_path, nextjs_port)
            if nextjs_port is not None
            else ""
        )
        setup_script = f"""
set -e
echo "Creating session directory: {session_path}"
mkdir -p {session_path}/outputs {session_path}/attachments {session_path}/.opencode
if [ -d {TEMPLATES_OUTPUTS_PATH} ]; then
    cp -r {TEMPLATES_OUTPUTS_PATH}/* {session_path}/outputs/
    # flock+sentinel: serialize concurrent session setups; .ready guards
    # against a partial cp from a previous interrupted run.
    (
        flock -x 9
        if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
            echo "Bootstrapping bun cache on workspace volume..."
            rm -rf {BUN_CACHE_DIR}
            cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \
                || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
            touch {BUN_CACHE_DIR}/.ready
        fi
    ) 9>{BUN_CACHE_DIR}.lock
    cd {session_path}/outputs/web && \
        BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \
        bun install --frozen-lockfile --backend=hardlink
else
    echo "Warning: outputs template not found at {TEMPLATES_OUTPUTS_PATH}"
    mkdir -p {session_path}/outputs/web
fi
ln -sf {MANAGED_SKILLS_PATH} {session_path}/.opencode/skills
printf '%s' '{agents_md}' > {session_path}/AGENTS.md
printf '%s' '{opencode_json}' > {session_path}/opencode.json
{nextjs_start}
echo "Session workspace setup complete"
"""

        logger.info(
            "Setting up session workspace %s in sandbox %s", session_id, sandbox_id
        )
        try:
            run_in_container(container, ["/bin/sh", "-c", setup_script])
        except ExecError as e:
            raise RuntimeError(
                f"Failed to setup session workspace {session_id}: {e}"
            ) from e

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,  # noqa: ARG002
    ) -> None:
        container = self._get_container(sandbox_id)
        if container is None:
            logger.debug(
                "Container missing while cleaning up session %s — already gone",
                session_id,
            )
            return

        session_path = f"{SESSIONS_ROOT}/{session_id}"
        cleanup_script = f"""
set -e
if [ -f {session_path}/nextjs.pid ]; then
    NEXTJS_PID=$(cat {session_path}/nextjs.pid)
    kill $NEXTJS_PID 2>/dev/null || true
fi
rm -rf {session_path}
echo "Session cleanup complete"
"""
        try:
            run_in_container(container, ["/bin/sh", "-c", cleanup_script])
        except ExecError as e:
            logger.warning(
                "cleanup_session_workspace exec failed for session %s: %s",
                session_id,
                e,
            )

    # ------------------------------------------------------------------
    # Workspace queries
    # ------------------------------------------------------------------

    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        container = self._get_container(sandbox_id)
        if container is None:
            return False
        target = f"{SESSIONS_ROOT}/{session_id}/outputs"
        try:
            result = run_in_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f'[ -d "{target}" ] && echo "WORKSPACE_FOUND" || echo "WORKSPACE_MISSING"',
                ],
                check=False,
            )
        except ExecError as e:
            logger.warning(
                "session_workspace_exists exec failed for sandbox %s: %s",
                sandbox_id,
                e,
            )
            return False
        return "WORKSPACE_FOUND" in result.stdout_text

    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        container = self._get_container(sandbox_id)
        if container is None:
            return []
        try:
            result = run_in_container(
                container,
                ["/bin/sh", "-c", f"ls -1 {SESSIONS_ROOT}/ 2>/dev/null || true"],
                check=False,
            )
        except ExecError as e:
            logger.warning(
                "list_session_workspaces exec failed for sandbox %s: %s",
                sandbox_id,
                e,
            )
            return []
        out: list[UUID] = []
        for line in result.stdout_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(UUID(line))
            except ValueError:
                continue
        return out

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        container = self._get_container(sandbox_id)
        if container is None:
            logger.info("create_snapshot: sandbox %s has no container", sandbox_id)
            return None

        session_path = f"{SESSIONS_ROOT}/{session_id}"
        # Bail out if there's nothing worth snapshotting.
        try:
            probe = run_in_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f'[ -d "{session_path}/outputs" ] && echo OK || echo EMPTY',
                ],
                check=False,
            )
        except ExecError:
            return None
        if "OK" not in probe.stdout_text:
            return None

        # Stream tar bytes out of the container through FileStore.
        tar_cmd = [
            "/bin/sh",
            "-c",
            (
                f"cd {session_path} && tar -czf - "
                f"$([ -d outputs ] && echo outputs) "
                f"$([ -d attachments ] && echo attachments) "
                f"$([ -d .opencode-data ] && echo .opencode-data)"
            ),
        ]

        stream = stream_stdout_from_container(container, tar_cmd)
        adapter = _GeneratorReader(stream)
        try:
            # ``_GeneratorReader`` satisfies the structural ``read(n)`` API
            # that ``SnapshotManager``/``FileStore`` actually use, but does
            # not subclass ``typing.IO[bytes]`` formally.
            _, storage_path, size_bytes = (
                self._snapshot_manager.create_snapshot_from_stream(
                    stream=adapter,  # ty: ignore[invalid-argument-type]
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create snapshot via stream: {e}") from e

        logger.info(
            "Created snapshot for sandbox %s session %s (size=%s bytes)",
            sandbox_id,
            session_id,
            size_bytes,
        )
        return SnapshotResult(storage_path=storage_path, size_bytes=size_bytes)

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,  # noqa: ARG002
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
    ) -> None:
        container = self._require_container(sandbox_id)
        session_path = f"{SESSIONS_ROOT}/{session_id}"

        # Make sure the session directory exists before we extract into it.
        try:
            run_in_container(
                container,
                ["/bin/sh", "-c", f"mkdir -p {session_path}"],
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to prepare session dir: {e}") from e

        # FileStore -> tar bytes -> remote ``tar -x`` stdin.
        # We have to materialize the bytes once because docker exec's stdin
        # needs to know the payload up front to be reliably consumed.
        buf = io.BytesIO()
        self._snapshot_manager.restore_snapshot_to_stream(snapshot_storage_path, buf)
        payload = buf.getvalue()

        try:
            stream_stdin_to_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f"cd {session_path} && tar -xzf -",
                ],
                payload,
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to extract snapshot: {e}") from e

        # Keep in sync with the K8s sandbox_daemon's restore_snapshot.
        install_script = f"""
set -e
web_dir={session_path}/outputs/web
if [ -f "$web_dir/bun.lock" ]; then
    (
        flock -x 9
        if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
            rm -rf {BUN_CACHE_DIR}
            cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \\
                || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
            touch {BUN_CACHE_DIR}/.ready
        fi
    ) 9>{BUN_CACHE_DIR}.lock
    cd "$web_dir"
    BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
fi
"""
        try:
            run_in_container(container, ["/bin/sh", "-c", install_script])
        except ExecError as e:
            raise RuntimeError(f"Failed to reinstall deps after restore: {e}") from e

        self._regenerate_session_config(
            container=container,
            session_path=session_path,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
        )

        if nextjs_port is not None:
            start_script = _build_nextjs_start_script(
                session_path, nextjs_port, check_node_modules=True
            )
            try:
                run_in_container(container, ["/bin/sh", "-c", start_script])
            except ExecError as e:
                raise RuntimeError(f"Failed to start Next.js after restore: {e}") from e

    def _regenerate_session_config(
        self,
        *,
        container: Container,
        session_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
    ) -> None:
        """Rewrite AGENTS.md, opencode.json, and the skills symlink post-restore.

        The snapshot tar only carries ``outputs/``, ``attachments/``, and
        ``.opencode-data/`` — the symlink and config files are regenerated
        here so restored sessions still see the pushed skill files.
        """
        agents_md, opencode_json = self._render_session_files(
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
        )
        script = f"""
set -e
mkdir -p {session_path}/.opencode
ln -sfn {MANAGED_SKILLS_PATH} {session_path}/.opencode/skills
printf '%s' '{agents_md}' > {session_path}/AGENTS.md
printf '%s' '{opencode_json}' > {session_path}/opencode.json
"""
        try:
            run_in_container(container, ["/bin/sh", "-c", script])
        except ExecError as e:
            raise RuntimeError(f"Failed to regenerate session config: {e}") from e

    # ------------------------------------------------------------------
    # ACP messaging
    # ------------------------------------------------------------------

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        container = self._require_container(sandbox_id)
        session_path = f"{SESSIONS_ROOT}/{session_id}"
        packet_logger = get_packet_logger()

        if container.name is None:
            raise RuntimeError(f"sandbox container for {sandbox_id} has no name")
        client = DockerACPExecClient(
            docker_client=self._docker, container_name=container.name
        )
        client.start(cwd=session_path)

        try:
            acp_session_id = client.resume_or_create_session(cwd=session_path)
            packet_logger.log_session_start(session_id, sandbox_id, message)

            events_count = 0
            try:
                for event in client.send_message(message, session_id=acp_session_id):
                    events_count += 1
                    yield event
                packet_logger.log_session_end(
                    session_id, success=True, events_count=events_count
                )
            except GeneratorExit:
                try:
                    client.cancel(session_id=acp_session_id)
                except Exception:
                    pass
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error="GeneratorExit",
                    events_count=events_count,
                )
                raise
            except Exception as e:
                try:
                    client.cancel(session_id=acp_session_id)
                except Exception:
                    pass
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error=str(e),
                    events_count=events_count,
                )
                raise
        finally:
            try:
                client.stop()
            except Exception as e:
                logger.warning("Failed to stop DockerACPExecClient: %s", e)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        container = self._require_container(sandbox_id)
        clean_path = _sanitize_relative_path(path)
        target_path = f"{SESSIONS_ROOT}/{session_id}/{clean_path}"
        quoted = shlex.quote(target_path)

        try:
            result = run_in_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f"ls -laL --time-style=+%s {quoted} 2>/dev/null || echo 'ERROR_NOT_FOUND'",
                ],
                check=False,
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to list directory: {e}") from e

        output = result.stdout_text
        if "ERROR_NOT_FOUND" in output:
            raise ValueError(f"Path not found or not a directory: {path}")

        entries = self._parse_ls_output(output, clean_path)
        return sorted(entries, key=lambda e: (not e.is_directory, e.name.lower()))

    def _parse_ls_output(self, ls_output: str, base_path: str) -> list[FilesystemEntry]:
        entries: list[FilesystemEntry] = []
        for line in ls_output.strip().split("\n"):
            if line.startswith("total") or not line:
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            is_symlink = line.startswith("l")
            if is_symlink and " -> " in line:
                name_and_target = " ".join(parts[6:])
                name = (
                    name_and_target.split(" -> ")[0]
                    if " -> " in name_and_target
                    else parts[-1]
                )
            else:
                name = " ".join(parts[6:])

            if name in (".", ".."):
                continue

            is_directory = line.startswith("d")
            size_str = parts[4]
            try:
                size = int(size_str) if not is_directory else None
            except ValueError:
                size = None
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
        container = self._require_container(sandbox_id)
        clean_path = _sanitize_relative_path(path)
        target_path = f"{SESSIONS_ROOT}/{session_id}/{clean_path}"
        quoted = shlex.quote(target_path)

        try:
            result = run_in_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f"if [ -f {quoted} ]; then base64 {quoted}; else echo 'ERROR_NOT_FOUND'; fi",
                ],
                check=False,
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

        if "ERROR_NOT_FOUND" in result.stdout_text:
            raise ValueError(f"File not found: {path}")
        try:
            return base64.b64decode(result.stdout_text.strip())
        except binascii.Error as e:
            raise RuntimeError(f"Failed to decode file content: {e}") from e

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        container = self._require_container(sandbox_id)
        target_dir = f"{SESSIONS_ROOT}/{session_id}/{ATTACHMENTS_DIRECTORY}"

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        tar_data = tar_buffer.getvalue()
        tar_size = len(tar_data)

        # Script reads exactly tar_size bytes from stdin (avoids needing EOF
        # because docker exec stdin closes cleanly when we shutdown(WR)).
        script = f"""
set -e
target_dir="{target_dir}"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$target_dir"
head -c {tar_size} | tar xf - -C "$tmpdir"

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
            result = stream_stdin_to_container(
                container, ["/bin/sh", "-c", script], tar_data
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to upload file: {e}") from e

        out_lines = [
            line.strip()
            for line in result.stdout_text.strip().split("\n")
            if line.strip()
        ]
        if not out_lines:
            raise RuntimeError(
                f"Upload failed - no filename returned. stderr: {result.stderr_text}"
            )
        final_filename = out_lines[-1]
        self._ensure_agents_md_attachments_section(container, session_id)
        return f"{ATTACHMENTS_DIRECTORY}/{final_filename}"

    def _ensure_agents_md_attachments_section(
        self, container: Container, session_id: UUID
    ) -> None:
        session_path = f"{SESSIONS_ROOT}/{session_id}"
        agents_md_path = f"{session_path}/AGENTS.md"
        attachments_b64 = base64.b64encode(
            ATTACHMENTS_SECTION_CONTENT.encode()
        ).decode()
        script = f"""
if [ -f "{agents_md_path}" ]; then
    if ! grep -q "## Attachments (PRIORITY)" "{agents_md_path}" 2>/dev/null; then
        if grep -q "## Skills" "{agents_md_path}" 2>/dev/null; then
            awk -v content="$(echo "{attachments_b64}" | base64 -d)" '
                /^## Skills/ {{ print content; print ""; }}
                {{ print }}
            ' "{agents_md_path}" > "{agents_md_path}.tmp" && mv "{agents_md_path}.tmp" "{agents_md_path}"
            echo "ADDED_BEFORE_SKILLS"
        else
            echo "" >> "{agents_md_path}"
            echo "" >> "{agents_md_path}"
            echo "{attachments_b64}" | base64 -d >> "{agents_md_path}"
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
            run_in_container(container, ["/bin/sh", "-c", script], check=False)
        except ExecError as e:
            logger.warning("AGENTS.md attachments section update failed: %s", e)

    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        container = self._require_container(sandbox_id)
        _validate_strict_path(path)
        clean_path = path.lstrip("/")
        target = f"{SESSIONS_ROOT}/{session_id}/{clean_path}"
        try:
            result = run_in_container(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f'[ -f "{target}" ] && rm "{target}" && echo "DELETED" || echo "NOT_FOUND"',
                ],
                check=False,
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to delete file: {e}") from e
        return "DELETED" in result.stdout_text

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

        container = self._require_container(sandbox_id)
        full_path = f"{WORKSPACE_ROOT}/{path}"
        safe_path = shlex.quote(full_path)
        safe_dir = shlex.quote(full_path.rsplit("/", 1)[0])
        escaped = content.replace("'", "'\\''")

        script = f"""set -e
mkdir -p {safe_dir}
printf '%s' '{escaped}' > {safe_path}
echo WRITE_OK"""
        try:
            result = run_in_container(container, ["/bin/sh", "-c", script])
        except ExecError as e:
            raise RuntimeError(f"Failed to write sandbox file {path}: {e}") from e
        if "WRITE_OK" not in result.stdout_text:
            raise RuntimeError(
                f"write_sandbox_file failed for {path}: {result.stdout_text}"
            )

    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        container = self._get_container(sandbox_id)
        if container is None:
            return 0, 0
        target_dir = f"{SESSIONS_ROOT}/{session_id}/{ATTACHMENTS_DIRECTORY}"
        cmd = (
            f'if [ -d "{target_dir}" ]; then\n'
            f'  count=$(find "{target_dir}" -maxdepth 1 -type f 2>/dev/null | wc -l)\n'
            f'  size=$(du -sb "{target_dir}" 2>/dev/null | cut -f1)\n'
            f'  echo "$count $size"\n'
            f"else\n"
            f'  echo "0 0"\n'
            f"fi"
        )
        try:
            result = run_in_container(container, ["/bin/sh", "-c", cmd], check=False)
        except ExecError as e:
            logger.warning("get_upload_stats failed: %s", e)
            return 0, 0
        parts = result.stdout_text.strip().split()
        if len(parts) >= 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return 0, 0
        return 0, 0

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        """Push a tar archive of ``files`` into the sandbox container.

        Docker V1 uses ``docker exec tar -x`` instead of the K8s sidecar's
        signed HTTP push — same outcome (files atomically land under
        ``mount_path``) without the keypair/HTTP plumbing.

        ``mount_path`` matches the K8s push-daemon contract: an absolute
        path inside the sandbox container (e.g. ``/workspace/managed/skills``).
        """
        if not mount_path:
            raise ValueError("mount_path is required")
        if ".." in Path(mount_path).parts:
            raise ValueError("mount_path may not contain '..'")
        container = self._require_container(sandbox_id)

        # Build a deterministic tar (sorted, fixed mtime) like the K8s push.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
            for name in sorted(files):
                data = files[name]
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mtime = 0
                info.uid = 1000
                info.gid = 1000
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        target = mount_path
        # Land atomically: extract into a temp dir alongside the target, then
        # rename. Matches the K8s push daemon's atomic-swap semantics.
        script = (
            f"set -e\n"
            f'target="{target}"\n'
            f'parent=$(dirname "$target")\n'
            f'mkdir -p "$parent"\n'
            f'tmpdir=$(mktemp -d -p "$parent")\n'
            f"trap 'rm -rf \"$tmpdir\"' EXIT\n"
            f'tar -xzf - -C "$tmpdir"\n'
            f'if [ -e "$target" ] && [ ! -L "$target" ]; then\n'
            f'    rm -rf "$target"\n'
            f"fi\n"
            f'if [ -L "$target" ]; then rm -f "$target"; fi\n'
            f'mv "$tmpdir" "$target"\n'
            f"trap - EXIT\n"
        )
        try:
            stream_stdin_to_container(container, ["/bin/sh", "-c", script], tar_bytes)
        except ExecError as e:
            raise RuntimeError(f"write_files_to_sandbox failed: {e}") from e

    # ------------------------------------------------------------------
    # Webapp / preview
    # ------------------------------------------------------------------

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Return an http URL the api_server can reach the sandbox on.

        api_server joins the sandbox bridge network in the compose file, so
        it can resolve the container by name on the sandbox network. If
        the manager runs outside that network, deployers can override via
        a Docker-discovered IP path in a follow-up.
        """
        container = self._get_container(sandbox_id)
        if container is None:
            return f"http://{_sandbox_container_name(sandbox_id)}:{port}"
        return f"http://{container.name}:{port}"

    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        container = self._require_container(sandbox_id)
        clean_pptx = _sanitize_relative_path(pptx_path)
        clean_cache = _sanitize_relative_path(cache_dir)
        session_root = f"{SESSIONS_ROOT}/{session_id}"
        pptx_abs = f"{session_root}/{clean_pptx}"
        cache_abs = f"{session_root}/{clean_cache}"

        try:
            result = run_in_container(
                container,
                [
                    "python",
                    f"{MANAGED_SKILLS_PATH}/pptx/scripts/preview.py",
                    pptx_abs,
                    cache_abs,
                ],
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to generate PPTX preview: {e}") from e

        lines = [
            line.strip()
            for line in result.stdout_text.strip().split("\n")
            if line.strip()
        ]
        if not lines:
            raise ValueError("Empty response from PPTX conversion")
        if lines[0] == "ERROR_NOT_FOUND":
            raise ValueError(f"File not found: {pptx_path}")
        if lines[0] == "ERROR_NO_PDF":
            raise ValueError("soffice did not produce a PDF file")

        cached = lines[0] == "CACHED"
        abs_paths = lines[1:] if lines[0] in ("CACHED", "GENERATED") else lines
        prefix = f"{session_root}/"
        rel_paths: list[str] = []
        for p in abs_paths:
            if p.startswith(prefix):
                rel_paths.append(p[len(prefix) :])
            elif p.endswith(".jpg"):
                rel_paths.append(p)
        return rel_paths, cached


class _GeneratorReader:
    """Adapt a ``Generator[bytes, ...]`` into a ``read(n)``-based reader.

    ``SnapshotManager.create_snapshot_from_stream`` (and ``shutil.copyfileobj``
    under it) only need ``read(n)``. We buffer leftover bytes so the
    producer's chunk size doesn't constrain the consumer's.
    """

    def __init__(self, gen: Generator[bytes, None, int]) -> None:
        self._gen = gen
        self._buf = b""

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data = self._buf + b"".join(self._gen)
            self._buf = b""
            return data
        while len(self._buf) < size:
            try:
                self._buf += next(self._gen)
            except StopIteration:
                break
        data, self._buf = self._buf[:size], self._buf[size:]
        return data

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        self._gen.close()
