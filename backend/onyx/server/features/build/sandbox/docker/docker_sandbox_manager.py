"""Docker-Engine-backed sandbox manager for self-hosted Onyx deployments.

Symmetric with ``KubernetesSandboxManager``: one container per user, sessions
are subdirectories under ``/workspace/sessions/`` inside the container, and
every operation goes through ``docker exec`` (the Docker analog of
``kubectl exec``). Snapshots tar the session directory inside the container,
stream the bytes back through the SDK socket, and hand them to the existing
``FileStore`` abstraction — no s5cmd sidecar, no IRSA, no init container.

Runtime deps:
- ``SANDBOX_BACKEND=docker`` selected in ``configs.py``
- The api_server has access to the Docker daemon (typically by mounting
  ``/var/run/docker.sock``; see ``deployment/docker_compose/docker-compose.yml``).
- The api_server and sandbox containers share a Docker bridge network
  (``SANDBOX_DOCKER_NETWORK``) so the api_server can reach NextJS dev
  servers by container hostname.

Trust boundary: mounting the docker socket is equivalent to root on the host.
This is documented in ``sandbox/README.md`` and is the same trust model the
helm chart inherits via the ``sandbox-runner`` ServiceAccount.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shlex
import tarfile
import threading
from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from uuid import UUID

import docker  # type: ignore[import-untyped]
from docker.errors import APIError  # type: ignore[import-untyped]
from docker.errors import ImageNotFound  # type: ignore[import-untyped]
from docker.errors import NotFound  # type: ignore[import-untyped]
from docker.models.containers import Container  # type: ignore[import-untyped]

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_DOCKER_CPU_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_HOST
from onyx.server.features.build.configs import SANDBOX_DOCKER_MEMORY_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_NETWORK
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker.internal.acp_exec_client import ACPEvent
from onyx.server.features.build.sandbox.docker.internal.acp_exec_client import (
    ACPExecClient,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    DockerExecError,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import exec_shell
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    exec_stream_stdout,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    exec_write_stdin,
)
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager
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

# Same convention as the K8s manager: container/pod name = "sandbox-{first 8 chars of UUID}".
# Keeping the shape parallel makes log greps work across deployments.
_CONTAINER_NAME_PREFIX = "sandbox-"

# Default user inside the sandbox image (matches the Dockerfile's UID/GID).
_SANDBOX_USER = "1000:1000"

# Resource defaults for the volume — the container holds /workspace/sessions/
# on this volume. Image-baked content (templates, skills, venv) lives inside
# the image itself so we don't need to bind-mount anything from the host.
_VOLUME_NAME_PREFIX = "onyx_sandbox_"


def _container_name(sandbox_id: UUID | str) -> str:
    return f"{_CONTAINER_NAME_PREFIX}{str(sandbox_id)[:8]}"


def _volume_name(sandbox_id: UUID | str) -> str:
    return f"{_VOLUME_NAME_PREFIX}{str(sandbox_id)[:8]}"


def _build_nextjs_start_script(
    session_path: str,
    nextjs_port: int,
    check_node_modules: bool = False,
) -> str:
    """Same shape as the K8s helper — kept duplicated rather than imported to
    avoid a fragile cross-package dependency on a shell-script string. If the
    two ever diverge, divergence is the bug to fix, not the duplication."""
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
echo "Starting Next.js dev server on port {nextjs_port}..."
nohup npm run dev -- -p {nextjs_port} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
"""


class DockerSandboxManager(SandboxManager):
    """Docker-Engine-backed sandbox manager (self-hosted production).

    Singleton. Mirrors ``KubernetesSandboxManager`` in shape and orchestration
    so callers can treat the two interchangeably; only the transport changes.
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
        if SANDBOX_DOCKER_HOST:
            self._client = docker.DockerClient(base_url=SANDBOX_DOCKER_HOST)
        else:
            self._client = docker.from_env()
        self._image = SANDBOX_CONTAINER_IMAGE
        self._network = SANDBOX_DOCKER_NETWORK
        self._cpu_limit = SANDBOX_DOCKER_CPU_LIMIT
        self._memory_limit = SANDBOX_DOCKER_MEMORY_LIMIT

        build_dir = Path(__file__).parent.parent.parent  # /onyx/server/features/build/
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"
        self._skills_path = build_dir / "sandbox" / "kubernetes" / "docker" / "skills"

        self._snapshot_manager = SnapshotManager(get_default_file_store())

        self._ensure_network()

        logger.info(
            f"DockerSandboxManager initialized: image={self._image} network={self._network} "
            f"cpu={self._cpu_limit} memory={self._memory_limit}"
        )

    def supports_idle_cleanup(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_network(self) -> None:
        """Create the shared bridge network if it doesn't already exist.

        Idempotent: 409 / "already exists" means another api_server replica
        beat us to it, which is fine.
        """
        try:
            self._client.networks.get(self._network)
            return
        except NotFound:
            pass

        try:
            self._client.networks.create(self._network, driver="bridge")
            logger.info(f"Created docker bridge network {self._network}")
        except APIError as e:
            if "already exists" in str(e).lower():
                return
            raise

    def _get_container(self, sandbox_id: UUID) -> Container:
        try:
            return self._client.containers.get(_container_name(sandbox_id))
        except NotFound as e:
            raise RuntimeError(f"Sandbox container for {sandbox_id} not found") from e

    def _container_or_none(self, sandbox_id: UUID) -> Container | None:
        try:
            return self._client.containers.get(_container_name(sandbox_id))
        except NotFound:
            return None

    def _container_is_healthy(self, container: Container) -> bool:
        container.reload()
        # "running" is good. "created" / "restarting" are transient — wait elsewhere.
        if container.status == "running":
            return True
        return False

    def _ensure_volume(self, sandbox_id: UUID) -> str:
        name = _volume_name(sandbox_id)
        try:
            self._client.volumes.get(name)
        except NotFound:
            self._client.volumes.create(name=name, driver="local")
            logger.debug(f"Created docker volume {name}")
        return name

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
        return generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_path=self._skills_path,
            files_path=None,  # generated inside container at runtime
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port,
            disabled_tools=disabled_tools,
            user_name=user_name,
            user_role=user_role,
            use_demo_data=use_demo_data,
            include_org_info=include_org_info,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,  # noqa: ARG002
    ) -> SandboxInfo:
        """Provision the user's sandbox container.

        Idempotent: if a healthy container with the expected name already
        exists, reuse it. If a stopped one exists, start it. If a wedged
        one exists, recreate it.
        """
        logger.info(
            f"Starting Docker sandbox provisioning for sandbox {sandbox_id}, user {user_id}, tenant {tenant_id}"
        )

        name = _container_name(sandbox_id)
        existing = self._container_or_none(sandbox_id)
        if existing is not None:
            existing.reload()
            if existing.status == "running":
                logger.info(f"Container {name} already running, reusing")
                return SandboxInfo(
                    sandbox_id=sandbox_id,
                    directory_path=f"docker://{name}",
                    status=SandboxStatus.RUNNING,
                    last_heartbeat=None,
                )
            if existing.status in {"exited", "created"}:
                try:
                    existing.start()
                    existing.reload()
                    if existing.status == "running":
                        logger.info(f"Started existing container {name}")
                        return SandboxInfo(
                            sandbox_id=sandbox_id,
                            directory_path=f"docker://{name}",
                            status=SandboxStatus.RUNNING,
                            last_heartbeat=None,
                        )
                except APIError as e:
                    logger.warning(
                        f"Failed to start existing container {name}: {e}, will recreate"
                    )
            # Wedged — recreate
            logger.warning(
                f"Container {name} in unexpected state {existing.status}, recreating"
            )
            try:
                existing.remove(force=True)
            except APIError as e:
                logger.warning(f"Failed to remove wedged container {name}: {e}")

        volume_name = self._ensure_volume(sandbox_id)

        try:
            container = self._client.containers.run(
                image=self._image,
                name=name,
                detach=True,
                # Keep the main process alive so we can exec into it. The image
                # has its own entrypoint that already serves this purpose, but
                # we override with a sleep loop in case the image entrypoint
                # exits prematurely or assumes K8s-only init.
                command=["/bin/sh", "-c", "while sleep 86400; do :; done"],
                user=_SANDBOX_USER,
                network=self._network,
                hostname=name,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=False,
                # Image-baked content (templates, skills, venv) is in the image.
                # Sessions live on a docker volume so we control lifecycle.
                volumes={
                    volume_name: {"bind": "/workspace/sessions", "mode": "rw"},
                },
                mem_limit=self._memory_limit,
                nano_cpus=int(self._cpu_limit * 1_000_000_000),
                labels={
                    "app.kubernetes.io/component": "sandbox",
                    "app.kubernetes.io/managed-by": "onyx",
                    "onyx.app/sandbox-id": str(sandbox_id),
                    "onyx.app/tenant-id": tenant_id,
                    "onyx.app/user-id": str(user_id),
                },
                restart_policy={"Name": "no"},
            )
        except ImageNotFound as e:
            raise RuntimeError(
                f"Sandbox image not available locally: {self._image}. "
                "Pull it on the host or set SANDBOX_CONTAINER_IMAGE."
            ) from e
        except APIError as e:
            if "Conflict" in str(e) or "already in use" in str(e).lower():
                logger.warning(
                    f"Concurrent provisioning detected for {name}, fetching existing container"
                )
                container = self._get_container(sandbox_id)
            else:
                raise RuntimeError(
                    f"Failed to provision Docker sandbox {sandbox_id}: {e}"
                ) from e

        # Make sure /workspace/sessions exists with the right perms.
        try:
            exec_shell(
                container,
                "mkdir -p /workspace/sessions && chmod 0775 /workspace/sessions",
                user="root",
            )
        except DockerExecError as e:
            logger.warning(f"Failed to prepare /workspace/sessions in {name}: {e}")

        logger.info(f"Provisioned Docker sandbox {sandbox_id} as container {name}")

        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=f"docker://{name}",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def terminate(self, sandbox_id: UUID) -> None:
        name = _container_name(sandbox_id)
        container = self._container_or_none(sandbox_id)
        if container is not None:
            try:
                container.remove(force=True)
                logger.info(f"Removed sandbox container {name}")
            except APIError as e:
                logger.error(f"Failed to remove container {name}: {e}")

        volume_name = _volume_name(sandbox_id)
        try:
            volume = self._client.volumes.get(volume_name)
            volume.remove(force=True)
            logger.debug(f"Removed sandbox volume {volume_name}")
        except NotFound:
            pass
        except APIError as e:
            logger.warning(f"Failed to remove volume {volume_name}: {e}")

    def health_check(
        self, sandbox_id: UUID, timeout: float = 60.0  # noqa: ARG002
    ) -> bool:
        container = self._container_or_none(sandbox_id)
        if container is None:
            return False
        return self._container_is_healthy(container)

    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        container = self._container_or_none(sandbox_id)
        if container is None:
            return []
        try:
            output = exec_shell(
                container,
                "ls -1 /workspace/sessions/ 2>/dev/null || echo ''",
            )
        except DockerExecError as e:
            logger.warning(
                f"Failed to list session workspaces in {container.name}: {e}"
            )
            return []
        sessions: list[UUID] = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(UUID(line))
            except ValueError:
                continue
        return sessions

    # ------------------------------------------------------------------
    # Session workspace setup
    # ------------------------------------------------------------------
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
        excluded_user_library_paths: list[str] | None = None,
    ) -> None:
        # file_system_path / excluded_user_library_paths intentionally unused —
        # the V1 plan moves knowledge retrieval to the HTTP search tool (project #1)
        # rather than syncing the corpus into the sandbox.
        del file_system_path, excluded_user_library_paths

        if snapshot_path:
            logger.warning(
                f"Snapshot restoration requested via setup_session_workspace; "
                f"use restore_snapshot() instead. Path={snapshot_path} ignored."
            )

        container = self._get_container(sandbox_id)
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

        opencode_config = build_opencode_config(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            api_key=llm_config.api_key if llm_config.api_key else None,
            api_base=llm_config.api_base,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
        )
        opencode_json = json.dumps(opencode_config)
        opencode_json_escaped = opencode_json.replace("'", "'\\''")
        agent_instructions_escaped = agent_instructions.replace("'", "'\\''")

        org_info_setup = ""
        if user_work_area:
            persona = get_persona_info(user_work_area, user_level)
            if persona:
                agents_md_escaped = ORG_INFO_AGENTS_MD.replace("'", "'\\''")
                identity_escaped = generate_user_identity_content(persona).replace(
                    "'", "'\\''"
                )
                org_structure_escaped = json.dumps(
                    ORGANIZATION_STRUCTURE, indent=2
                ).replace("'", "'\\''")
                org_info_setup = f"""
mkdir -p {session_path}/org_info
printf '%s' '{agents_md_escaped}' > {session_path}/org_info/AGENTS.md
printf '%s' '{identity_escaped}' > {session_path}/org_info/user_identity_profile.txt
printf '%s' '{org_structure_escaped}' > {session_path}/org_info/organization_structure.json
"""

        # files/ behavior: The K8s backend symlinks to either /workspace/files
        # (S3-synced) or /workspace/demo_data. Per the V1 plan, /workspace/files
        # is empty in docker mode (search becomes an HTTP tool). We still create
        # an empty files/ directory so AGENTS.md tooling that references it
        # doesn't break.
        if use_demo_data:
            files_setup = (
                f"# Demo data symlink (image-baked)\n"
                f"ln -sf /workspace/demo_data {session_path}/files\n"
            )
        else:
            files_setup = (
                f"# files/ is empty in docker mode (search is provided via the HTTP tool, project #1)\n"
                f"mkdir -p {session_path}/files\n"
            )

        outputs_setup = f"""
# Copy outputs template baked into the image and install npm deps.
echo "Copying outputs template"
if [ -d /workspace/templates/outputs ]; then
    cp -r /workspace/templates/outputs/* {session_path}/outputs/
    cd {session_path}/outputs/web && npm install
else
    echo "Warning: outputs template not found at /workspace/templates/outputs"
    mkdir -p {session_path}/outputs/web
fi
"""

        nextjs_start_script = _build_nextjs_start_script(
            session_path, nextjs_port, check_node_modules=False
        )

        setup_script = f"""
set -e

echo "Creating session directory: {session_path}"
mkdir -p {session_path}/outputs
mkdir -p {session_path}/attachments

{files_setup}

{outputs_setup}

# Symlink skills (baked into image at /workspace/skills/)
if [ -d /workspace/skills ]; then
    mkdir -p {session_path}/.opencode
    ln -sf /workspace/skills {session_path}/.opencode/skills
fi

echo "Writing AGENTS.md"
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md

# Best-effort knowledge-source rendering. Continues if the script is missing.
python3 /usr/local/bin/generate_agents_md.py {session_path}/AGENTS.md {session_path}/files || true

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
            exec_shell(container, setup_script)
        except DockerExecError as e:
            logger.error(
                f"Failed to setup session workspace {session_id} in sandbox {sandbox_id}: {e}"
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
        container = self._container_or_none(sandbox_id)
        if container is None:
            logger.debug(
                f"Container for sandbox {sandbox_id} gone, skipping session cleanup"
            )
            return
        session_path = f"/workspace/sessions/{session_id}"
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
            exec_shell(container, cleanup_script)
        except DockerExecError as e:
            logger.warning(f"Error cleaning up session workspace {session_id}: {e}")

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def session_workspace_exists(self, sandbox_id: UUID, session_id: UUID) -> bool:
        container = self._container_or_none(sandbox_id)
        if container is None:
            return False
        path = f"/workspace/sessions/{session_id}/outputs"
        try:
            exec_shell(container, f"[ -d {shlex.quote(path)} ]")
            return True
        except DockerExecError:
            return False

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        container = self._get_container(sandbox_id)
        session_path = f"/workspace/sessions/{session_id}"
        safe_session_path = shlex.quote(session_path)

        # Discover what's actually present so tar doesn't error on missing dirs.
        try:
            check = exec_shell(
                container,
                f"""
set -e
cd {safe_session_path} 2>/dev/null || {{ echo "EMPTY_SNAPSHOT"; exit 0; }}
[ -d outputs ] || {{ echo "EMPTY_SNAPSHOT"; exit 0; }}
parts="outputs"
[ -d attachments ] && [ -n "$(ls -A attachments 2>/dev/null)" ] && parts="$parts attachments"
[ -d .opencode-data ] && [ -n "$(ls -A .opencode-data 2>/dev/null)" ] && parts="$parts .opencode-data"
echo "READY:$parts"
""",
            )
        except DockerExecError as e:
            raise RuntimeError(f"Failed to inspect session for snapshot: {e}") from e

        if "EMPTY_SNAPSHOT" in check:
            logger.info(
                f"No outputs to snapshot for session {session_id} in sandbox {sandbox_id}"
            )
            return None

        # Last "READY:..." line tells us what tar should include.
        ready_line = next(
            (line for line in check.strip().splitlines() if line.startswith("READY:")),
            "",
        )
        components = ready_line.removeprefix("READY:").strip()
        if not components:
            logger.info(f"No components to snapshot for session {session_id}")
            return None

        cmd = [
            "/bin/sh",
            "-c",
            f"cd {safe_session_path} && tar -czf - {components}",
        ]

        # Stream tar bytes into the file store. We pipe through a BytesIO so
        # SnapshotManager (which expects a seekable BinaryIO) can checksum and
        # upload. For multi-GB snapshots this would want a chunked uploader,
        # but V1 keeps things simple.
        buf = BytesIO()
        try:
            for chunk in exec_stream_stdout(self._client, container, cmd):
                buf.write(chunk)
        except DockerExecError as e:
            raise RuntimeError(f"tar failed during snapshot: {e}") from e
        buf.seek(0)

        try:
            snapshot_id, storage_path, size_bytes = (
                self._snapshot_manager.create_snapshot_from_stream(
                    stream=buf,
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )
        finally:
            buf.close()

        logger.info(
            f"Snapshot {snapshot_id} created for session {session_id} (size={size_bytes})"
        )
        return SnapshotResult(storage_path=storage_path, size_bytes=size_bytes)

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,  # noqa: ARG002
        nextjs_port: int,
        llm_config: LLMProviderConfig,
        use_demo_data: bool = False,
    ) -> None:
        container = self._get_container(sandbox_id)
        session_path = f"/workspace/sessions/{session_id}"
        safe_session_path = shlex.quote(session_path)

        # Pull bytes from the file store into memory, then push through the
        # exec stdin into ``tar -xzf -`` inside the container.
        stream = self._snapshot_manager.restore_snapshot_to_stream(
            snapshot_storage_path
        )
        try:
            payload = stream.read()
        finally:
            try:
                stream.close()
            except Exception:
                pass

        cmd = [
            "/bin/sh",
            "-c",
            f"mkdir -p {safe_session_path} && tar -xzf - -C {safe_session_path}",
        ]
        try:
            exec_write_stdin(self._client, container, cmd, payload)
        except DockerExecError as e:
            raise RuntimeError(f"tar -xzf failed during restore: {e}") from e

        # Regenerate per-deployment configuration that's not in the snapshot.
        self._regenerate_session_config(
            container=container,
            session_path=session_path,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            use_demo_data=use_demo_data,
        )

        # Start Next.js (npm install in case node_modules is missing or stale).
        try:
            exec_shell(
                container,
                _build_nextjs_start_script(
                    session_path, nextjs_port, check_node_modules=True
                ),
            )
        except DockerExecError as e:
            raise RuntimeError(f"Failed to start Next.js after restore: {e}") from e

    def _regenerate_session_config(
        self,
        container: Container,
        session_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int,
        use_demo_data: bool,
    ) -> None:
        agent_instructions = self._load_agent_instructions(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=None,
            user_role=None,
            use_demo_data=use_demo_data,
            include_org_info=False,
        )
        opencode_config = build_opencode_config(
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            api_key=llm_config.api_key if llm_config.api_key else None,
            api_base=llm_config.api_base,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
        )
        opencode_json = json.dumps(opencode_config)
        opencode_json_escaped = opencode_json.replace("'", "'\\''")
        agent_instructions_escaped = agent_instructions.replace("'", "'\\''")

        if use_demo_data:
            files_setup = f"ln -sf /workspace/demo_data {session_path}/files\n"
        else:
            files_setup = f"mkdir -p {session_path}/files\n"

        config_script = f"""
set -e
{files_setup}
printf '%s' '{agent_instructions_escaped}' > {session_path}/AGENTS.md
python3 /usr/local/bin/generate_agents_md.py {session_path}/AGENTS.md {session_path}/files || true
printf '%s' '{opencode_json_escaped}' > {session_path}/opencode.json
"""
        try:
            exec_shell(container, config_script)
        except DockerExecError as e:
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
        packet_logger = get_packet_logger()
        session_path = f"/workspace/sessions/{session_id}"
        container = self._get_container(sandbox_id)

        acp_client = ACPExecClient(
            container_name=container.name,
            docker_client=self._client,
        )
        acp_client.start(cwd=session_path)

        try:
            acp_session_id = acp_client.resume_or_create_session(cwd=session_path)
            packet_logger.log_session_start(session_id, sandbox_id, message)

            events_count = 0
            try:
                for event in acp_client.send_message(
                    message, session_id=acp_session_id
                ):
                    events_count += 1
                    yield event
                packet_logger.log_session_end(
                    session_id, success=True, events_count=events_count
                )
            except GeneratorExit:
                try:
                    acp_client.cancel(session_id=acp_session_id)
                except Exception as cancel_err:
                    logger.warning(
                        f"[SANDBOX-ACP-DOCKER] session/cancel failed on GeneratorExit: {cancel_err}"
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error="GeneratorExit",
                    events_count=events_count,
                )
                raise
            except Exception as e:
                try:
                    acp_client.cancel(session_id=acp_session_id)
                except Exception as cancel_err:
                    logger.warning(
                        f"[SANDBOX-ACP-DOCKER] session/cancel failed on Exception: {cancel_err}"
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error=f"Exception: {e}",
                    events_count=events_count,
                )
                raise
        finally:
            try:
                acp_client.stop()
            except Exception as e:
                logger.warning(
                    f"[SANDBOX-ACP-DOCKER] Failed to stop ACP client: session={session_id} error={e}"
                )

    # ------------------------------------------------------------------
    # Filesystem operations
    # ------------------------------------------------------------------
    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        container = self._get_container(sandbox_id)
        path_obj = Path(path.lstrip("/"))
        clean_parts = [p for p in path_obj.parts if p != ".."]
        clean_path = str(Path(*clean_parts)) if clean_parts else "."
        target_path = f"/workspace/sessions/{session_id}/{clean_path}"
        quoted = shlex.quote(target_path)
        try:
            output = exec_shell(
                container,
                f"ls -laL --time-style=+%s {quoted} 2>/dev/null || echo 'ERROR_NOT_FOUND'",
            )
        except DockerExecError as e:
            raise RuntimeError(f"Failed to list directory: {e}") from e

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

            is_directory = line.startswith("d") or is_symlink
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
        container = self._get_container(sandbox_id)
        path_obj = Path(path.lstrip("/"))
        clean_parts = [p for p in path_obj.parts if p != ".."]
        clean_path = str(Path(*clean_parts)) if clean_parts else "."
        target_path = f"/workspace/sessions/{session_id}/{clean_path}"

        # Use docker's get_archive to pull the file as a tar. Avoids base64
        # encoding overhead and handles binary data cleanly.
        try:
            stream, _ = container.get_archive(target_path)
        except NotFound as e:
            raise ValueError(f"File not found: {path}") from e
        except APIError as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

        buf = BytesIO()
        for chunk in stream:
            buf.write(chunk)
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:*") as tar:
            members = [m for m in tar.getmembers() if m.isfile()]
            if not members:
                raise ValueError(f"Not a file: {path}")
            extracted = tar.extractfile(members[0])
            if extracted is None:
                raise ValueError(f"Could not extract: {path}")
            return extracted.read()

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        container = self._get_container(sandbox_id)
        target_dir = f"/workspace/sessions/{session_id}/attachments"

        # Build a tar in memory containing just this file.
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content)
            info.mode = 0o644
            tar.addfile(info, BytesIO(content))
        tar_bytes = buf.getvalue()

        # Ensure target directory exists.
        try:
            exec_shell(container, f"mkdir -p {shlex.quote(target_dir)}")
        except DockerExecError as e:
            raise RuntimeError(f"Failed to prepare attachments dir: {e}") from e

        # Resolve filename collisions: pick a non-existing name before extracting.
        final_name = self._pick_unique_attachment_name(container, target_dir, filename)
        if final_name != filename:
            buf2 = BytesIO()
            with tarfile.open(fileobj=buf2, mode="w") as tar:
                info = tarfile.TarInfo(name=final_name)
                info.size = len(content)
                info.mode = 0o644
                tar.addfile(info, BytesIO(content))
            tar_bytes = buf2.getvalue()

        try:
            ok = container.put_archive(path=target_dir, data=tar_bytes)
            if not ok:
                raise RuntimeError("put_archive returned False")
        except APIError as e:
            raise RuntimeError(f"Failed to upload file: {e}") from e

        # Best-effort: ensure AGENTS.md surfaces the attachments section.
        self._ensure_agents_md_attachments_section(container, session_id)
        logger.info(
            f"Uploaded file to session {session_id}: attachments/{final_name} ({len(content)} bytes)"
        )
        return f"attachments/{final_name}"

    def _pick_unique_attachment_name(
        self, container: Container, target_dir: str, filename: str
    ) -> str:
        """Return ``filename`` if free, otherwise ``stem_N.ext``."""
        try:
            existing = exec_shell(
                container,
                f"ls -1 {shlex.quote(target_dir)} 2>/dev/null || true",
            )
        except DockerExecError:
            existing = ""
        existing_set = {line.strip() for line in existing.split("\n") if line.strip()}
        if filename not in existing_set:
            return filename
        stem, dot, ext = filename.rpartition(".")
        if not dot:
            stem, ext = filename, ""
        else:
            ext = "." + ext
        i = 1
        while f"{stem}_{i}{ext}" in existing_set:
            i += 1
        return f"{stem}_{i}{ext}"

    def _ensure_agents_md_attachments_section(
        self, container: Container, session_id: UUID
    ) -> None:
        agents_md_path = f"/workspace/sessions/{session_id}/AGENTS.md"
        # Use base64 to safely embed multi-line content in shell.
        import base64

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
        else
            echo "" >> "{agents_md_path}"
            echo "" >> "{agents_md_path}"
            echo "{attachments_b64}" | base64 -d >> "{agents_md_path}"
        fi
    fi
fi
"""
        try:
            exec_shell(container, script)
        except DockerExecError as e:
            logger.warning(f"Failed to ensure AGENTS.md attachments section: {e}")

    def delete_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bool:
        container = self._get_container(sandbox_id)
        # Same path-validation rules as the K8s implementation.
        if re.search(r"\.\.", path) or "%" in path or "\x00" in path:
            raise ValueError("Invalid path: potential path traversal detected")
        if re.search(r'[;&|`$(){}[\]<>\'"\n\r\\]', path):
            raise ValueError("Invalid path: contains disallowed characters")
        clean_path = path.lstrip("/")
        if not re.match(r"^[a-zA-Z0-9_\-./]+$", clean_path):
            raise ValueError("Invalid path: contains disallowed characters")
        target = f"/workspace/sessions/{session_id}/{clean_path}"
        try:
            output = exec_shell(
                container,
                f'[ -f "{target}" ] && rm "{target}" && echo "DELETED" || echo "NOT_FOUND"',
            )
        except DockerExecError as e:
            raise RuntimeError(f"Failed to delete file: {e}") from e
        return "DELETED" in output

    def get_upload_stats(self, sandbox_id: UUID, session_id: UUID) -> tuple[int, int]:
        container = self._container_or_none(sandbox_id)
        if container is None:
            return 0, 0
        target_dir = f"/workspace/sessions/{session_id}/attachments"
        try:
            output = exec_shell(
                container,
                f"""
if [ -d "{target_dir}" ]; then
    count=$(find "{target_dir}" -maxdepth 1 -type f 2>/dev/null | wc -l)
    size=$(du -sb "{target_dir}" 2>/dev/null | cut -f1)
    echo "$count $size"
else
    echo "0 0"
fi
""",
            )
        except DockerExecError as e:
            logger.warning(f"Failed to get upload stats: {e}")
            return 0, 0
        parts = output.strip().split()
        if len(parts) >= 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                logger.warning(f"Failed to parse upload stats: {output}")
        return 0, 0

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        # Reachable from the api_server over the shared bridge network.
        return f"http://{_container_name(sandbox_id)}:{port}"

    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        container = self._get_container(sandbox_id)

        pptx_path_obj = Path(pptx_path.lstrip("/"))
        pptx_clean_parts = [p for p in pptx_path_obj.parts if p != ".."]
        clean_pptx = str(Path(*pptx_clean_parts)) if pptx_clean_parts else "."

        cache_path_obj = Path(cache_dir.lstrip("/"))
        cache_clean_parts = [p for p in cache_path_obj.parts if p != ".."]
        clean_cache = str(Path(*cache_clean_parts)) if cache_clean_parts else "."

        session_root = f"/workspace/sessions/{session_id}"
        pptx_abs = f"{session_root}/{clean_pptx}"
        cache_abs = f"{session_root}/{clean_cache}"

        try:
            output = exec_shell(
                container,
                shlex.join(
                    [
                        "python",
                        "/workspace/skills/pptx/scripts/preview.py",
                        pptx_abs,
                        cache_abs,
                    ]
                ),
            )
        except DockerExecError as e:
            raise RuntimeError(f"Failed to generate PPTX preview: {e}") from e

        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]
        if not lines:
            raise ValueError("Empty response from PPTX conversion")
        if lines[0] == "ERROR_NOT_FOUND":
            raise ValueError(f"File not found: {pptx_path}")
        if lines[0] == "ERROR_NO_PDF":
            raise ValueError("soffice did not produce a PDF file")

        cached = lines[0] == "CACHED"
        abs_paths = lines[1:] if lines[0] in ("CACHED", "GENERATED") else lines
        prefix = f"{session_root}/"
        rel: list[str] = []
        for p in abs_paths:
            if p.startswith(prefix):
                rel.append(p[len(prefix) :])
            elif p.endswith(".jpg"):
                rel.append(p)
        return rel, cached

    def sync_files(
        self,
        sandbox_id: UUID,
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
        source: str | None = None,  # noqa: ARG002
    ) -> bool:
        """No-op for docker mode.

        Per the V1 plan, knowledge retrieval moves to the HTTP search tool
        (project #1) rather than syncing the corpus into the sandbox. We keep
        this method as a no-op so callers (e.g. the indexing post-write hook)
        don't need to special-case backends.
        """
        logger.debug(f"sync_files called for docker sandbox {sandbox_id} - no-op")
        return True


# Re-exported so kubernetes-equivalent imports still resolve from a clean path.
__all__ = ["DockerSandboxManager"]
