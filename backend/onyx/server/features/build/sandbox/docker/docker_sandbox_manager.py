"""Docker-based sandbox manager for self-hosted docker-compose deployments.

This is the docker-compose analogue of :class:`KubernetesSandboxManager`. The
api_server mounts the Docker socket and drives container lifecycle
(provision/terminate, exec into the sandbox for setup, file ops, and agent
messaging) the same way the K8s manager drives the Kubernetes API.

User-shared sandbox model
-------------------------
One container per user, multiple sessions under ``/workspace/sessions``,
matching the K8s pod model. ``provision()`` creates a single container and a
per-sandbox named volume mounted at ``/workspace/sessions``.

Snapshots
---------
Docker V1 streams tar bytes through api_server-owned ``FileStore`` rather than
handing storage credentials to the agent container. ``create_snapshot`` runs
``tar`` inside the sandbox via docker exec, pipes the bytes through
``SnapshotManager.persist_snapshot_from_stream``; ``restore_snapshot`` runs the
reverse path via ``stream_stdin_to_container``.

Security model
--------------
Sandbox containers run with:

- ``--security-opt no-new-privileges``
- ``--cap-drop ALL``
- ``user=1000:1000``
- no Docker socket mount
- no S3 / MinIO / Postgres / Redis / FileStore credentials in env
- a fixed env allowlist (``ONYX_PAT``, ``ONYX_SERVER_URL``,
  opencode auth/config only)
- only the dedicated sandbox bridge network — never compose's default
  network. As a result api_server / postgres / redis / minio /
  model_server are NOT reachable by service name from inside the sandbox.

Threat model — Docker vs Kubernetes parity gap
----------------------------------------------
The LLM provider ``api_key`` is passed into the container via
``OPENCODE_CONFIG_CONTENT`` (a plaintext Docker env var visible to ``docker
inspect``). K8s loads the same config from an RBAC-scoped ``Secret``. Treat host
access to the Docker daemon as access to the key; see
``docs/craft/docker-opencode-serve.md`` for the operator-facing note.

Outbound communication is intentionally limited to:

1. Public internet over HTTPS (the bridge has default internet egress; block at
   the host's ``DOCKER-USER`` chain if you need a stricter posture, e.g. for EC2
   IMDS).
2. The Onyx API via ``ONYX_SERVER_URL`` — which must be the *public* HTTPS URL
   the agent reaches just like any other onyx-cli client.

Most control-plane traffic from api_server → sandbox uses the Docker
Engine API (``docker exec``). Prompt/event transport uses opencode-serve over
the sandbox bridge; host-run dev-mode connectivity lives in ``dev_mode_serve``.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import mimetypes
import re
import secrets
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

from onyx.configs.app_configs import DEV_MODE
from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import ATTACHMENTS_DIRECTORY
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import OPENCODE_SERVE_PORT
from onyx.server.features.build.configs import OPENCODE_SERVER_PASSWORD
from onyx.server.features.build.configs import SANDBOX_API_SERVER_URL
from onyx.server.features.build.configs import SANDBOX_CONTAINER_IMAGE
from onyx.server.features.build.configs import SANDBOX_DOCKER_CPU_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_MEMORY_LIMIT
from onyx.server.features.build.configs import SANDBOX_DOCKER_NETWORK
from onyx.server.features.build.configs import SANDBOX_DOCKER_SOCKET
from onyx.server.features.build.configs import SANDBOX_DOCKER_VOLUME_PREFIX
from onyx.server.features.build.configs import SANDBOX_PROXY_CA_VOLUME_NAME
from onyx.server.features.build.configs import SANDBOX_PROXY_HOST
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.configs import SANDBOX_PROXY_PORT
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR
from onyx.server.features.build.sandbox.base import BUN_IMAGE_CACHE_DIR
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker.dev_mode_serve import (
    opencode_serve_port_bindings,
)
from onyx.server.features.build.sandbox.docker.dev_mode_serve import (
    published_opencode_serve_base_url,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import ExecError
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import ExecResult
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    run_in_container,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    stream_stdin_to_container,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    stream_stdout_from_container,
)
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY_ONYX
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.labels import LABEL_TENANT_ID
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
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


LABEL_COMPONENT = "onyx.app/component"
LABEL_COMPONENT_VALUE = "craft-sandbox"
LABEL_USER_ID = "onyx.app/user-id"

# Path conventions inside the sandbox container — must match the K8s image.
WORKSPACE_ROOT = "/workspace"
SESSIONS_ROOT = f"{WORKSPACE_ROOT}/sessions"
# Opencode's data home (its XDG_DATA_HOME); matches entrypoint.sh's default. It
# lives in the container writable layer, not the per-sandbox volume, so it is
# durable only via the FileStore history snapshot. Its basename must equal the
# daemon archive's root dir, so put_archive at WORKSPACE_ROOT lands the restored
# tree here (see _maybe_restore_opencode_history).
OPENCODE_DATA_DIR = f"{WORKSPACE_ROOT}/.opencode-data"
TEMPLATES_OUTPUTS_PATH = f"{WORKSPACE_ROOT}/templates/outputs"
MANAGED_SKILLS_PATH = f"{WORKSPACE_ROOT}/managed/skills"
MANAGED_USER_LIBRARY_PATH = f"{WORKSPACE_ROOT}/managed/user_library"
SANDBOX_EXEC_USER = "1000:1000"
# Docker exec bypasses firewall-init.sh's setpriv environment workaround, so
# sandbox-user execs must carry the uid/gid and user HOME together.
SANDBOX_EXEC_ENV = {"HOME": "/home/sandbox", "USER": "sandbox"}
SANDBOX_TMP_PATH = "/tmp"  # noqa: S108 - sandbox-local scratch mount.
SANDBOX_TMPFS_OPTIONS = "rw,nosuid,nodev,size=5g,mode=1777"

# Mirror the K8s constants in ``kubernetes_sandbox_manager`` (POD_READY_*),
# which are also module-level and not env-tunable.
CONTAINER_READY_TIMEOUT_SECONDS = 120
CONTAINER_READY_POLL_INTERVAL_SECONDS = 1.0


# Egress proxy file paths inside the sandbox container. Matched by
# ``firewall-init.sh``: ``CA_SRC`` defaults to ``/sandbox-ca/ca.crt`` and
# ``CA_DST`` to ``/etc/ssl/sandbox/ca-bundle.crt``. The bundle dir lives in the
# container's writable layer (not a separate volume) since only the init step
# writes to it and only the agent reads it.
_PROXY_CA_SOURCE_DIR = "/sandbox-ca"
_PROXY_CA_BUNDLE_DIR = "/etc/ssl/sandbox"
_PROXY_CA_BUNDLE_FILE = f"{_PROXY_CA_BUNDLE_DIR}/ca-bundle.crt"

# Per-session egress tagging plugin, baked into the sandbox image (see
# kubernetes/docker/Dockerfile). Path must match the COPY destination there.
# Registered in the opencode config only when the proxy is wired up; otherwise
# it would no-op (no HTTP(S)_PROXY to re-tag).
_OPENCODE_SESSION_TAG_PLUGIN_PATH = "/workspace/opencode-plugins/session-proxy-tag.ts"
# Surfaces the no-op `connect_app` tool; always on. Its "ask" permission is what
# the api-server intercepts to drive the connect-app OAuth flow.
_OPENCODE_CONNECT_APP_PLUGIN_PATH = "/workspace/opencode-plugins/connect-app.ts"
_MUTABLE_SANDBOX_IMAGE_TAGS = {"latest", "beta", "edge"}

# In-container opencode-history archive builder: reuses the sandbox_daemon
# helper (sqlite-safe backup + symlink guards) and prints the temp archive path,
# or nothing when there's no history. Exec it with OPENCODE_DATA_HOME set.
_OPENCODE_HISTORY_CREATE_SCRIPT = (
    "import sys; "
    "from sandbox_daemon.opencode_history import create_opencode_history_archive_file; "
    "p = create_opencode_history_archive_file(); "
    "sys.stdout.write('' if p is None else str(p))"
)


def _run_in_container_as_sandbox_user(
    container: Container,
    command: list[str] | str,
    *,
    workdir: str | None = None,
    check: bool = True,
) -> ExecResult:
    return run_in_container(
        container,
        command,
        user=SANDBOX_EXEC_USER,
        workdir=workdir,
        environment=SANDBOX_EXEC_ENV,
        check=check,
    )


def _stream_stdin_to_container_as_sandbox_user(
    container: Container,
    command: list[str],
    payload: bytes,
    *,
    workdir: str | None = None,
) -> ExecResult:
    return stream_stdin_to_container(
        container,
        command,
        payload,
        user=SANDBOX_EXEC_USER,
        workdir=workdir,
        environment=SANDBOX_EXEC_ENV,
    )


def _stream_stdout_from_container_as_sandbox_user(
    container: Container,
    command: list[str],
    *,
    workdir: str | None = None,
    chunk_size: int = 64 * 1024,
) -> Generator[bytes, None, int]:
    return stream_stdout_from_container(
        container,
        command,
        user=SANDBOX_EXEC_USER,
        workdir=workdir,
        environment=SANDBOX_EXEC_ENV,
        chunk_size=chunk_size,
    )


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


def _sandbox_container_name(sandbox_id: str | UUID) -> str:
    """Container name derived from sandbox ID. Matches K8s ``sandbox-<id8>``."""
    return f"sandbox-{str(sandbox_id)[:8]}"


def _sandbox_volume_name(sandbox_id: str | UUID) -> str:
    """Per-sandbox named volume holding ``/workspace/sessions``."""
    return f"{SANDBOX_DOCKER_VOLUME_PREFIX}{str(sandbox_id)[:8]}"


def _container_llm_configs(
    all_llm_configs: list[LLMProviderConfig] | None,
    llm_config: LLMProviderConfig,
    *,
    proxy_enabled: bool,
) -> list[LLMProviderConfig]:
    """Provider configs to bake into the container's opencode.json.

    The Docker analog of K8s ``_placeholder_llm_configs``: when the egress proxy
    is enabled, real keys are swapped for the placeholder (the proxy injects the
    live key on the wire); ``api_key=None`` providers (e.g. Ollama) are left
    untouched so the placeholder never reaches the LLM.
    """
    configs = all_llm_configs or [llm_config]
    if not proxy_enabled:
        return configs
    return [
        c.model_copy(update={"api_key": SANDBOX_PROXY_INJECTED_PLACEHOLDER})
        if c.api_key
        else c
        for c in configs
    ]


def _sanitize_relative_path(path: str) -> str:
    """Strips ``..`` components and leading ``/`` from a user-provided path."""
    path_obj = Path(path.lstrip("/"))
    clean_parts = [p for p in path_obj.parts if p != ".."]
    return str(Path(*clean_parts)) if clean_parts else "."


def _validate_strict_path(path: str) -> None:
    """
    Rejects paths with traversal, URL escapes, null bytes, or shell
    metacharacters.
    """
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
    """Heuristic: Does ``url`` reference a compose-internal service hostname?

    Used to warn deployers that pointed SANDBOX_API_SERVER_URL at the
    api_server's compose DNS name. Sandboxes can't resolve that — they only join
    the craft bridge network — so the URL must be the public Onyx URL.
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
    outside compose (e.g. local tests) so the manager falls back to "ungrouped"
    sandbox containers.
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

    ``compose_project`` is added as ``com.docker.compose.project`` so Docker
    Desktop groups sandbox containers under the same "onyx" stack header as
    api_server/postgres/redis/etc. Auto-detected by ``DockerSandboxManager``
    from its own container's labels.
    """
    labels: dict[str, str] = {
        LABEL_COMPONENT: LABEL_COMPONENT_VALUE,
        LABEL_SANDBOX_ID: str(sandbox_id),
        LABEL_TENANT_ID: tenant_id,
        LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
    }
    if user_id is not None:
        labels[LABEL_USER_ID] = str(user_id)
    if compose_project:
        labels["com.docker.compose.project"] = compose_project
    return labels


# Sandbox should reach loopback directly; everything else (api server included)
# goes through the proxy.
_NO_PROXY_LIST = "127.0.0.1,localhost"


def _proxy_env_vars(
    *,
    sandbox_proxy_host: str,
) -> dict[str, str]:
    """Proxy-enabled env additions for the sandbox container.

    The Kubernetes lane injects the equivalent vars via the Helm pod template
    (``onyx.sandboxProxyEnv``); here they're layered on the docker env dict.
    Includes the firewall-init.sh contract vars since the script runs as the
    container's entrypoint wrapper and reads them from its own environment.
    Proxy ports come from build config and are injected as internal env, not
    caller arguments.
    """
    proxy_url = f"http://{sandbox_proxy_host}:{SANDBOX_PROXY_PORT}"
    return {
        # firewall-init.sh contract.
        "SANDBOX_PROXY_HOST": sandbox_proxy_host,
        "SANDBOX_PROXY_PORT": str(SANDBOX_PROXY_PORT),
        "SANDBOX_PROXY_BOOTSTRAP_MODE": "entrypoint",
        "SANDBOX_PROXY_CA_BUNDLE_SRC": f"{_PROXY_CA_SOURCE_DIR}/ca.crt",
        "SANDBOX_PROXY_CA_BUNDLE_DST": _PROXY_CA_BUNDLE_FILE,
        # Agent-side proxy + CA wiring.
        "HTTPS_PROXY": proxy_url,
        "HTTP_PROXY": proxy_url,
        "https_proxy": proxy_url,
        "http_proxy": proxy_url,
        "NO_PROXY": _NO_PROXY_LIST,
        "no_proxy": _NO_PROXY_LIST,
        # SDK-specific CA env vars for libs that bypass /etc/ssl/certs.
        "NODE_EXTRA_CA_CERTS": _PROXY_CA_BUNDLE_FILE,
        "REQUESTS_CA_BUNDLE": _PROXY_CA_BUNDLE_FILE,
        "SSL_CERT_FILE": _PROXY_CA_BUNDLE_FILE,
        "AWS_CA_BUNDLE": _PROXY_CA_BUNDLE_FILE,
        "CURL_CA_BUNDLE": _PROXY_CA_BUNDLE_FILE,
        "GIT_SSL_CAINFO": _PROXY_CA_BUNDLE_FILE,
        "GH_TOKEN": SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        "GH_NO_UPDATE_NOTIFIER": "1",
    }


class _ContainerCreateKwargsRequired(TypedDict):
    """
    Always-set fields. Security-critical ones (cap_drop, security_opt,
    privileged, user) live here so omitting them fails type-check.
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
    ports: dict[str, tuple[str, int | None]]
    environment: dict[str, str]
    volumes: dict[str, dict[str, str]]
    tmpfs: dict[str, str]
    mem_limit: str
    nano_cpus: int
    restart_policy: dict[str, str]


class ContainerCreateKwargs(_ContainerCreateKwargsRequired, total=False):
    """
    Kwargs we pass to ``DockerClient.containers.run``. Proxy-mode adds
    ``cap_add`` and ``entrypoint`` (the image bakes ENTRYPOINT, which Docker
    would otherwise prepend to ``command``, silently breaking the
    firewall-init.sh handoff).
    """

    cap_add: list[str]
    entrypoint: list[str]


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
    opencode_password: str,
    opencode_config_json: str,
    compose_project: str | None = None,
    sandbox_proxy_host: str | None = None,
    proxy_ca_volume_name: str | None = None,
) -> ContainerCreateKwargs:
    """Builds the kwargs dict for ``DockerClient.containers.create``.

    Two postures gated on ``sandbox_proxy_host`` truthiness:

    Legacy (proxy disabled, default in tests/dev without proxy stack):

    - **Env is a fixed allowlist**: ONYX_PAT, ONYX_SERVER_URL, plus
      ``OPENCODE_SERVER_PASSWORD`` and ``OPENCODE_CONFIG_CONTENT``.
      No caller can inject anything else. No S3/MinIO/Postgres/Redis
      credentials. No compose service hostnames.
    - **No host mounts**: only the per-sandbox named volume mounted at
      ``/workspace/sessions``. No Docker socket. No FileStore root.
    - **Cap-dropped non-root**: ``user=1000:1000``, ``cap_drop=ALL``,
      ``security_opt=no-new-privileges``, ``privileged=False``.
    - **Single network**: joins only the caller-supplied ``network`` (the
      dedicated ``onyx_craft_sandbox`` bridge). Does NOT join compose's default
      network; api_server / postgres / redis / minio are unreachable by service
      name.

    Proxy-enabled (``sandbox_proxy_host`` set; production self-host compose with
    ``--include-craft``):

    - Env layered with ``HTTPS_PROXY`` / SDK CA vars + the ``firewall-init.sh``
      contract vars (``SANDBOX_PROXY_HOST``, ``SANDBOX_PROXY_PORT``,
      ``SANDBOX_PROXY_BOOTSTRAP_MODE=entrypoint``, ``CA_BUNDLE_SRC``/``DST``).
      The legacy 4-key core is preserved; proxy keys
      are layered on top.
    - ``ONYX_PAT`` and the opencode ``api_key`` are replaced with
      ``SANDBOX_PROXY_INJECTED_PLACEHOLDER``; the proxy reads the real values
      from Postgres and injects them on the wire (OnyxPatResolver,
      LLMProviderKeyResolver). The sandbox never sees the raw credentials.
    - ``entrypoint=["/workspace/firewall-init.sh"]`` overrides the image's baked
      ENTRYPOINT (which Docker would otherwise prepend to ``command``, silently
      bypassing the init); ``command=["/workspace/entrypoint.sh"]`` becomes the
      arg firewall-init.sh exec's after setpriv drops caps + switches to UID
      1000.
    - ``cap_add=["NET_ADMIN", "SETPCAP", "SETUID", "SETGID", "CHOWN"]``
      (NET_ADMIN runs iptables; SETPCAP authorises
      ``setpriv --bounding-set=-all``; SETUID/SETGID gate setpriv's
      ``--reuid``/``--regid`` under ``cap_drop=ALL``; CHOWN repairs the
      sessions volume mount-point owner). All five leave the bounding set
      before the agent
      execve, so the running container ends up with no caps at all.
    - ``user="0:0"`` so the init starts as root for iptables. setpriv then drops
      to UID 1000. The root+NET_ADMIN window is bounded by ``firewall-init.sh``
      runtime (~seconds); ``set -euo pipefail`` + ``die`` short-circuit on any
      step failure, so a broken init exits non-zero before the agent ever
      starts. ``restart_policy: unless-stopped`` re-enters the same fail-fast
      init -- no cumulative exposure, no user code reachable during the window.
    - The named proxy-CA volume is mounted read-only at ``/sandbox-ca`` for
      ``firewall-init.sh`` to read ``ca.crt``. That volume also contains
      root-only ``ca.key``; the agent runs as UID 1000 after init.

    ``ONYX_SERVER_URL`` must be the *public* Onyx URL (the one onyx-cli inside
    the sandbox will hit over HTTPS) — not an internal compose DNS name. We emit
    a warning if it looks like the latter, since reaching it would require the
    sandbox to be on the compose default network.

    ``opencode_password`` is generated per-provision by the manager and injected
    as the env var named by ``OPENCODE_SERVER_PASSWORD``. The api_server reads
    it back via ``docker inspect`` rather than persisting it on disk.
    ``opencode_config_json`` is the full ``opencode.json`` content
    (single-provider for Docker today), surfaced as ``OPENCODE_CONFIG_CONTENT``
    for opencode-serve to load at startup.
    """
    if _looks_like_internal_compose_host(api_server_url):
        logger.warning(
            "SANDBOX_API_SERVER_URL=%s looks like an internal compose hostname. Sandboxes only "
            "join the craft bridge network and reach the API server like any other public client, "
            "so this URL must resolve publicly (e.g. https://onyx.your-org.com). Internal DNS will "
            "fail and the agent will see 'connection refused'.",
            api_server_url,
        )

    env: dict[str, str] = {
        "ONYX_PAT": onyx_pat,
        "ONYX_SERVER_URL": api_server_url,
        OPENCODE_SERVER_PASSWORD: opencode_password,
        "OPENCODE_CONFIG_CONTENT": opencode_config_json,
    }

    security_opts = ["no-new-privileges:true"]
    ports: dict[str, tuple[str, int | None]] = {}
    if DEV_MODE:
        # Host-run dev workers are outside Docker's bridge DNS namespace, so
        # they cannot reach http://sandbox-<id>:4096 directly. Publish only in
        # dev mode, bound to localhost, while full compose uses bridge DNS.
        ports = opencode_serve_port_bindings()
    volumes: dict[str, dict[str, str]] = {
        volume_name: {"bind": SESSIONS_ROOT, "mode": "rw"},
    }

    if sandbox_proxy_host:
        # All-or-nothing: ca volume must be supplied when host is.
        if not proxy_ca_volume_name:
            raise ValueError(
                "sandbox_proxy_host is set but proxy_ca_volume_name is missing; "
                "Proxy posture requires both."
            )
        env.update(
            _proxy_env_vars(
                sandbox_proxy_host=sandbox_proxy_host,
            )
        )
        volumes[proxy_ca_volume_name] = {
            "bind": _PROXY_CA_SOURCE_DIR,
            "mode": "ro",
        }
        # Override the image's ENTRYPOINT (set to entrypoint.sh in #11748);
        # Without this, Docker prepends entrypoint.sh and our firewall-init
        # never runs -- the proxy lockdown + setpriv drop are silently skipped.
        entrypoint = ["/workspace/firewall-init.sh"]
        command = ["/workspace/entrypoint.sh"]
        user = "0:0"
        # NET_ADMIN: iptables. SETPCAP: prctl(PR_CAPBSET_DROP) for `setpriv
        # --bounding-set=-all`. SETUID/SETGID: setpriv's --reuid/--regid call
        # setuid()/setgroups(), which are gated on these caps even for UID 0
        # under cap_drop=ALL. CHOWN: repair /workspace/sessions mount-point
        # ownership before dropping to UID 1000. All five leave the bounding set
        # before the agent execve, so the running container ends up with no caps.
        cap_add = ["NET_ADMIN", "SETPCAP", "SETUID", "SETGID", "CHOWN"]
    else:
        entrypoint = None
        command = ["/workspace/entrypoint.sh"]
        user = "1000:1000"
        cap_add = []

    kwargs: ContainerCreateKwargs = {
        "name": _sandbox_container_name(sandbox_id),
        "image": image,
        "command": command,
        "detach": True,
        "labels": build_sandbox_labels(
            sandbox_id, tenant_id, user_id, compose_project=compose_project
        ),
        "user": user,
        "cap_drop": ["ALL"],
        "security_opt": security_opts,
        "privileged": False,
        "read_only": False,
        "network": network,
        "ports": ports,
        "environment": env,
        "volumes": volumes,
        "tmpfs": {SANDBOX_TMP_PATH: SANDBOX_TMPFS_OPTIONS},
        "mem_limit": memory_limit,
        "nano_cpus": int(cpu_limit * 1_000_000_000),
        "restart_policy": {"Name": "unless-stopped"},
        # No docker socket mount. No S3/MinIO env. No FileStore credentials.
    }
    if cap_add:
        kwargs["cap_add"] = cap_add
    if entrypoint is not None:
        kwargs["entrypoint"] = entrypoint
    return kwargs


class DockerSandboxManager(SandboxManager):
    """Sandbox manager that drives the host Docker Engine.

    Singleton; use :func:`get_sandbox_manager` to obtain the instance.
    """

    _instance: "DockerSandboxManager | None" = None
    _lock = threading.Lock()

    supports_opencode_history_persistence = True

    def __new__(cls) -> "DockerSandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    # Publish to the cache only after _initialize() succeeds, so
                    # a transient init failure (e.g. the Docker socket briefly
                    # unavailable) can't leave a half-built singleton that every
                    # later caller reuses; the next call retries instead.
                    instance = super().__new__(cls)
                    instance._initialize()
                    cls._instance = instance
        return cls._instance

    def _initialize(self) -> None:
        # Mirrors the K8s posture from #11604: the proxy is mandatory whenever
        # craft is enabled.
        if not SANDBOX_PROXY_HOST:
            raise RuntimeError(
                "DockerSandboxManager requires SANDBOX_PROXY_HOST. The sandbox egress proxy is "
                "mandatory when craft is enabled; wire it in docker-compose.craft.yml or unset "
                "SANDBOX_BACKEND."
            )

        self._docker = DockerClient(base_url=f"unix://{SANDBOX_DOCKER_SOCKET}")
        self._image = SANDBOX_CONTAINER_IMAGE
        self._image_checked = False
        self._image_check_lock = threading.Lock()
        self._network_name = SANDBOX_DOCKER_NETWORK
        self._memory_limit = SANDBOX_DOCKER_MEMORY_LIMIT
        self._cpu_limit = SANDBOX_DOCKER_CPU_LIMIT
        self._snapshot_manager = SnapshotManager(get_default_file_store())

        self._init_serve_state()

        build_dir = Path(__file__).parent.parent.parent
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"

        # Match api_server's compose project so Docker Desktop groups sandboxes
        # under the same stack header; None outside compose.
        self._compose_project = _detect_compose_project(self._docker)

        logger.info(
            "DockerSandboxManager initialized: socket=%s image=%s network=%s "
            "compose_project=%s.",
            SANDBOX_DOCKER_SOCKET,
            self._image,
            self._network_name,
            self._compose_project,
        )

    def _ensure_sandbox_image(self) -> None:
        with self._image_check_lock:
            if self._image_checked:
                return

            image_tag: str | None = None
            # Digest refs use ``@sha256:...``; do not parse that colon as a tag.
            if "@" not in self._image:
                image_name = self._image.rsplit("/", 1)[-1]
                image_tag = (
                    image_name.rsplit(":", 1)[1] if ":" in image_name else "latest"
                )
            is_mutable_tag = image_tag in _MUTABLE_SANDBOX_IMAGE_TAGS
            if not is_mutable_tag:
                try:
                    self._docker.images.get(self._image)
                    self._image_checked = True
                    return
                except NotFound:
                    pass

            logger.info(
                "%s sandbox image %s.",
                "Refreshing" if is_mutable_tag else "Pulling missing",
                self._image,
            )
            try:
                self._docker.images.pull(self._image)
            except APIError as e:
                if not is_mutable_tag:
                    raise RuntimeError(
                        f"Failed to pull sandbox image {self._image}: {e}"
                    ) from e

                try:
                    self._docker.images.get(self._image)
                except NotFound:
                    raise RuntimeError(
                        f"Failed to pull sandbox image {self._image}: {e}"
                    ) from e
                logger.warning(
                    "Failed to refresh mutable sandbox image %s; using cached "
                    "local image: %s",
                    self._image,
                    e,
                )

            self._image_checked = True

    def _ensure_sandbox_network(self) -> None:
        try:
            self._docker.networks.get(self._network_name)
            return
        except NotFound:
            pass
        logger.info("Creating sandbox network: %s.", self._network_name)
        # Plain bridge (internal=False) — agent needs public internet; host
        # DOCKER-USER chain handles IMDS blocking.
        self._docker.networks.create(
            self._network_name,
            driver="bridge",
            labels={
                LABEL_COMPONENT: LABEL_COMPONENT_VALUE,
                LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
            },
        )

    def _ensure_sandbox_volume(self, sandbox_id: UUID, tenant_id: str) -> str:
        volume_name = _sandbox_volume_name(sandbox_id)
        try:
            self._docker.volumes.get(volume_name)
            return volume_name
        except NotFound:
            pass
        logger.info("Creating sandbox volume: %s.", volume_name)
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
                f"Sandbox {sandbox_id} container not found — call provision() first."
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
                    f"Sandbox container {container.name} exited unexpectedly. Logs:\n{logs[:2000]}"
                )
            time.sleep(CONTAINER_READY_POLL_INTERVAL_SECONDS)
        return False

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
        if not onyx_pat:
            raise ValueError("onyx_pat is required for Docker sandbox provisioning.")
        if not SANDBOX_API_SERVER_URL:
            raise ValueError(
                "SANDBOX_API_SERVER_URL must be set for Docker sandbox provisioning."
            )

        logger.info(
            "Provisioning Docker sandbox %s for user %s, tenant %s.",
            sandbox_id,
            user_id,
            tenant_id,
        )

        # Re-provision: clear tombstone + cached info so subscribes can build a
        # fresh bus against the new container.
        with self._event_buses_lock:
            self._terminated_sandboxes.discard(sandbox_id)
        self._invalidate_serve_connection_info(sandbox_id)

        container = self._reuse_existing_container(sandbox_id)
        created_fresh = False
        if container is None:
            # opencode-serve reads provider config from env at startup; must be
            # in create_kwargs before the container ever runs.
            opencode_password = secrets.token_urlsafe(32)
            # connect_app is always loaded; the egress-tagging plugin only when
            # the proxy is wired up (else it no-ops — no HTTP(S)_PROXY to re-tag).
            plugins = [_OPENCODE_CONNECT_APP_PLUGIN_PATH]
            if SANDBOX_PROXY_HOST:
                plugins.append(_OPENCODE_SESSION_TAG_PLUGIN_PATH)
            # Proxy posture: Real PAT + LLM api_key never enter the sandbox. The
            # proxy reads `Sandbox.encrypted_pat` and the per-provider key from
            # Postgres, swaps the placeholder for the real bearer on the wire
            # (OnyxPatResolver, LLMProviderKeyResolver).
            container_onyx_pat = (
                SANDBOX_PROXY_INJECTED_PLACEHOLDER if SANDBOX_PROXY_HOST else onyx_pat
            )
            provider_configs = _container_llm_configs(
                all_llm_configs, llm_config, proxy_enabled=bool(SANDBOX_PROXY_HOST)
            )
            opencode_config_json = json.dumps(
                build_multi_provider_opencode_config(
                    providers=provider_configs,
                    default_provider=llm_config.provider,
                    default_model=llm_config.model_name,
                    disabled_tools=OPENCODE_DISABLED_TOOLS,
                    plugins=plugins,
                )
            )
            self._ensure_sandbox_image()
            self._ensure_sandbox_network()
            volume_name = self._ensure_sandbox_volume(sandbox_id, tenant_id)
            container, created_fresh = self._create_sandbox_container(
                sandbox_id=sandbox_id,
                user_id=user_id,
                tenant_id=tenant_id,
                onyx_pat=container_onyx_pat,
                volume_name=volume_name,
                opencode_password=opencode_password,
                opencode_config_json=opencode_config_json,
            )

        if created_fresh:
            # Restore history into the empty writable layer before starting, so
            # opencode-serve opens the restored DB instead of creating an empty
            # one. On failure, remove the container so a retry re-creates
            # cleanly.
            try:
                self._maybe_restore_opencode_history(container, sandbox_id, tenant_id)
                container.start()
            except Exception as e:
                self._remove_incomplete_container(container)
                raise RuntimeError(
                    f"Failed to provision sandbox container {container.name}: {e}"
                ) from e

        if not self._wait_for_container_running(container):
            raise RuntimeError(
                f"Timeout waiting for sandbox container {container.name} to be running."
            )

        if not self._wait_for_opencode_serve_ready(sandbox_id):
            raise RuntimeError(
                f"opencode-serve never became ready in sandbox container {container.name}."
            )

        logger.info(
            "Provisioned Docker sandbox %s, container=%s.", sandbox_id, container.name
        )
        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=f"docker://{container.name}",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def _reuse_existing_container(self, sandbox_id: UUID) -> Container | None:
        """Returns a reusable running/exited container, else None.

        A ``created`` container means a prior provision died before start;
        starting it would skip the opencode-history restore, so remove it and
        let the caller re-create. The per-sandbox volume survives, so session
        workspaces are kept.
        """
        existing = self._get_container(sandbox_id)
        if existing is None:
            return None
        existing.reload()
        status = ((existing.attrs or {}).get("State") or {}).get("Status")
        if status == "running":
            logger.info("Reusing existing running sandbox %s.", sandbox_id)
            return existing
        if status == "exited":
            logger.info("Starting existing stopped sandbox %s.", existing.name)
            existing.start()
            return existing
        if status == "created":
            logger.warning(
                "Sandbox %s container is in 'created' state (incomplete prior "
                "provision); removing so it can be re-created and restored.",
                sandbox_id,
            )
            self._remove_incomplete_container(existing)
            return None
        return None

    @staticmethod
    def _remove_incomplete_container(container: Container) -> None:
        """Best-effort force-remove of a container we failed to fully provision."""
        try:
            container.remove(force=True)
        except (APIError, NotFound) as e:
            logger.warning(
                "Failed to remove incomplete sandbox container %s: %s",
                container.name,
                e,
            )

    def _create_sandbox_container(
        self,
        *,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str,
        volume_name: str,
        opencode_password: str,
        opencode_config_json: str,
    ) -> tuple[Container, bool]:
        """
        Creates (not starts) the container; returns ``(container,
        created_fresh)``.

        ``created_fresh`` is False only when a concurrent provision already
        created it (409 conflict); the caller then skips restore/start and lets
        that provisioner finish.
        """
        # Proxy posture is gated on SANDBOX_PROXY_HOST; threaded through
        # build_container_create_kwargs to layer on the legacy posture without
        # bifurcating this call site.
        proxy_host = SANDBOX_PROXY_HOST or None
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
            opencode_password=opencode_password,
            opencode_config_json=opencode_config_json,
            compose_project=self._compose_project,
            sandbox_proxy_host=proxy_host,
            proxy_ca_volume_name=(SANDBOX_PROXY_CA_VOLUME_NAME if proxy_host else None),
        )
        # create (not run) so the caller can put_archive history before start.
        # detach is run-only.
        run_kwargs = dict(create_kwargs)
        run_kwargs.pop("detach", None)
        try:
            return self._docker.containers.create(**run_kwargs), True
        except APIError as e:
            if "Conflict" in str(e) or getattr(e, "status_code", None) == 409:
                logger.info("Sandbox container %s already exists, reusing.", sandbox_id)
                return self._require_container(sandbox_id), False
            raise RuntimeError(f"Failed to create sandbox container: {e}") from e

    def terminate(self, sandbox_id: UUID) -> None:
        self._close_all_sandbox_buses(sandbox_id)

        container = self._get_container(sandbox_id)
        if container is not None:
            try:
                container.remove(force=True, v=False)
                logger.info("Removed sandbox container %s.", container.name)
            except (APIError, NotFound) as e:
                logger.warning(
                    "Error removing sandbox container %s: %s", container.name, e
                )

        # Volume removal is separate so terminate works after manual container
        # rm.
        volume_name = _sandbox_volume_name(sandbox_id)
        try:
            volume = self._docker.volumes.get(volume_name)
            volume.remove(force=True)
            logger.info("Removed sandbox volume %s.", volume_name)
        except NotFound:
            pass
        except APIError as e:
            logger.warning("Error removing sandbox volume %s: %s", volume_name, e)

        logger.info("Terminated Docker sandbox %s.", sandbox_id)

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

    def _render_agents_md(
        self,
        *,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        connectable_apps_section: str,
        user_name: str | None = None,
    ) -> str:
        """Shell-escaped AGENTS.md for ``printf '%s' '...'``."""
        agent_instructions = generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
            provider=llm_config.provider,
            model_name=llm_config.model_name,
            nextjs_port=nextjs_port,
            disabled_tools=OPENCODE_DISABLED_TOOLS,
            user_name=user_name,
        )
        return agent_instructions.replace("'", "'\\''")

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
        container = self._require_container(sandbox_id)
        session_path = f"{SESSIONS_ROOT}/{session_id}"
        agents_md = self._render_agents_md(
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
            user_name=user_name,
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
ln -sf {MANAGED_USER_LIBRARY_PATH} {session_path}/user_library
printf '%s' '{agents_md}' > {session_path}/AGENTS.md
{nextjs_start}
echo "Session workspace setup complete"
"""

        logger.info(
            "Setting up session workspace %s in sandbox %s.", session_id, sandbox_id
        )
        try:
            # user="1000:1000": container's User spec is "0:0" (proxy init needs
            # root for iptables), so docker exec defaults to root. Without
            # CAP_DAC_OVERRIDE (cap_drop=ALL), root cannot write to
            # /workspace/sessions which is owned by sandbox=1000. Exec as
            # sandbox so the script's mkdir/cp on the session workspace succeed.
            _run_in_container_as_sandbox_user(
                container, ["/bin/sh", "-c", setup_script]
            )
        except ExecError as e:
            raise RuntimeError(
                f"Failed to setup session workspace {session_id}: {e}"
            ) from e

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        self._close_session_buses(sandbox_id, session_id)

        container = self._get_container(sandbox_id)
        if container is None:
            logger.debug(
                "Container missing while cleaning up session %s — already gone.",
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
            _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", cleanup_script],
            )
        except ExecError as e:
            logger.warning(
                "cleanup_session_workspace exec failed for session %s: %s",
                session_id,
                e,
            )

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
            result = _run_in_container_as_sandbox_user(
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
            result = _run_in_container_as_sandbox_user(
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

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        container = self._get_container(sandbox_id)
        if container is None:
            logger.info("create_snapshot: sandbox %s has no container.", sandbox_id)
            return None

        session_path = f"{SESSIONS_ROOT}/{session_id}"
        # Bail out if there's nothing worth snapshotting.
        try:
            probe = _run_in_container_as_sandbox_user(
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
                f"$([ -d attachments ] && echo attachments)"
            ),
        ]

        stream = _stream_stdout_from_container_as_sandbox_user(container, tar_cmd)
        adapter = _GeneratorReader(stream)
        try:
            # ``_GeneratorReader`` satisfies the structural ``read(n)`` API that
            # ``SnapshotManager``/``FileStore`` actually use, but does not
            # subclass ``typing.IO[bytes]`` formally.
            _, storage_path, size_bytes = (
                self._snapshot_manager.persist_snapshot_from_stream(
                    stream=adapter,  # ty: ignore[invalid-argument-type]
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create snapshot via stream: {e}") from e

        logger.info(
            "Created snapshot for sandbox %s session %s (size=%s bytes).",
            sandbox_id,
            session_id,
            size_bytes,
        )
        return SnapshotResult(storage_path=storage_path, size_bytes=size_bytes)

    def create_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = 300.0,  # noqa: ARG002 - exec uses the docker client timeout
    ) -> bool:
        """Captures sandbox-global opencode history to the FileStore.

        Returns False when opencode has written no data yet, leaving any
        existing durable archive untouched.
        """
        container = self._get_container(sandbox_id)
        if container is None:
            logger.info(
                "create_opencode_history_snapshot: sandbox %s has no container.",
                sandbox_id,
            )
            return False

        # Point the daemon helper at the Docker data home (unset in the container).
        history_env = {**SANDBOX_EXEC_ENV, "OPENCODE_DATA_HOME": OPENCODE_DATA_DIR}
        try:
            built = run_in_container(
                container,
                ["python3", "-c", _OPENCODE_HISTORY_CREATE_SCRIPT],
                user=SANDBOX_EXEC_USER,
                environment=history_env,
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to build opencode history archive: {e}") from e

        archive_path = built.stdout_text.strip()
        if not archive_path:
            logger.info("No opencode history to snapshot for sandbox %s.", sandbox_id)
            return False

        try:
            stream = _stream_stdout_from_container_as_sandbox_user(
                container, ["cat", archive_path]
            )
            # _GeneratorReader gives the read(n) API persist_* needs (not a typing.IO).
            adapter = _GeneratorReader(stream)
            storage_path, size_bytes = (
                self._snapshot_manager.persist_opencode_snapshot_from_stream(
                    stream=adapter,  # ty: ignore[invalid-argument-type]
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                )
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to persist opencode history snapshot: {e}"
            ) from e
        finally:
            # Drop the in-container temp archive regardless of outcome.
            try:
                run_in_container(
                    container,
                    ["rm", "-f", archive_path],
                    user=SANDBOX_EXEC_USER,
                    check=False,
                )
            except ExecError:
                pass

        logger.info(
            "Created opencode history snapshot for sandbox %s (path=%s size=%s bytes).",
            sandbox_id,
            storage_path,
            size_bytes,
        )
        return True

    def _maybe_restore_opencode_history(
        self,
        container: Container,
        sandbox_id: UUID,
        tenant_id: str,
    ) -> None:
        """
        Restores durable opencode history into a freshly-created,
        not-yet-started container, before opencode-serve opens its DB. No-op
        when no snapshot exists.

        Writing the stopped container's writable layer avoids racing a live
        opencode process over the DB file.
        """
        if not self._snapshot_manager.has_opencode_history_snapshot(
            tenant_id, str(sandbox_id)
        ):
            return

        storage_path = SnapshotManager.opencode_history_storage_path(
            tenant_id, str(sandbox_id)
        )
        buf = io.BytesIO()
        self._snapshot_manager.restore_snapshot_to_stream(storage_path, buf)
        archive_bytes = buf.getvalue()
        if not archive_bytes:
            logger.warning(
                "Opencode history snapshot for sandbox %s was empty; skipping restore.",
                sandbox_id,
            )
            return

        try:
            # put_archive untars (gzip ok) into the stopped container's writable layer.
            if not container.put_archive(WORKSPACE_ROOT, archive_bytes):
                raise RuntimeError("docker put_archive reported failure")
        except (APIError, NotFound) as e:
            raise RuntimeError(
                f"Failed to restore opencode history into sandbox {sandbox_id}: {e}"
            ) from e

        logger.info(
            "Restored opencode history into sandbox %s (%s bytes).",
            sandbox_id,
            len(archive_bytes),
        )

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
        container = self._require_container(sandbox_id)
        session_path = f"{SESSIONS_ROOT}/{session_id}"

        # Make sure the session directory exists before we extract into it.
        try:
            _run_in_container_as_sandbox_user(
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
            _stream_stdin_to_container_as_sandbox_user(
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
            _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", install_script],
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to reinstall deps after restore: {e}") from e

        self._regenerate_session_config(
            container=container,
            session_path=session_path,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
        )

        if nextjs_port is not None:
            start_script = _build_nextjs_start_script(
                session_path, nextjs_port, check_node_modules=True
            )
            try:
                _run_in_container_as_sandbox_user(
                    container,
                    ["/bin/sh", "-c", start_script],
                )
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
        connectable_apps_section: str,
    ) -> None:
        """
        Rewrite AGENTS.md and the skills symlink post-restore. opencode.json is
        not written — config lives at container scope via
        OPENCODE_CONFIG_CONTENT.
        """
        agents_md = self._render_agents_md(
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
        )
        script = f"""
set -e
mkdir -p {session_path}/.opencode
ln -sfn {MANAGED_SKILLS_PATH} {session_path}/.opencode/skills
ln -sfn {MANAGED_USER_LIBRARY_PATH} {session_path}/user_library
printf '%s' '{agents_md}' > {session_path}/AGENTS.md
"""
        try:
            _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", script],
            )
        except ExecError as e:
            raise RuntimeError(f"Failed to regenerate session config: {e}") from e

    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        """One ``docker inspect`` to extract URL + password.

        Compose deployments use container-name DNS on the sandbox bridge
        network. Host-run dev mode may override this with a localhost-published
        URL from ``dev_mode_serve``.
        """
        container = self._get_container(sandbox_id)
        if container is None:
            return None
        try:
            container.reload()
            attrs = container.attrs or {}
            env_list = (attrs.get("Config") or {}).get("Env") or []
        except (APIError, NotFound):
            return None
        password: str | None = None
        prefix = f"{OPENCODE_SERVER_PASSWORD}="
        for entry in env_list:
            if entry.startswith(prefix):
                password = entry[len(prefix) :]
                break
        base_url = f"http://{_sandbox_container_name(sandbox_id)}:{OPENCODE_SERVE_PORT}"
        if DEV_MODE:
            # Match the dev-only port publishing above: host-run workers need
            # the Docker-assigned localhost port, while compose should keep the
            # stable sandbox bridge URL.
            base_url = published_opencode_serve_base_url(attrs) or base_url
        return ServeConnectionInfo(
            base_url=base_url,
            password=password,
        )

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        container = self._require_container(sandbox_id)
        clean_path = _sanitize_relative_path(path)
        target_path = f"{SESSIONS_ROOT}/{session_id}/{clean_path}"
        quoted = shlex.quote(target_path)

        try:
            result = _run_in_container_as_sandbox_user(
                container,
                [
                    "/bin/sh",
                    "-c",
                    f"ls -la --time-style=+%s {quoted}/ 2>/dev/null || echo 'ERROR_NOT_FOUND'",
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
            link_target: str | None = None
            if is_symlink and " -> " in line:
                name_and_target = " ".join(parts[6:])
                if " -> " in name_and_target:
                    name, link_target = name_and_target.split(" -> ", 1)
                else:
                    name = parts[-1]
            else:
                name = " ".join(parts[6:])

            if name in (".", ".."):
                continue

            is_directory = line.startswith("d") or (
                is_symlink and link_target == MANAGED_USER_LIBRARY_PATH
            )
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
            result = _run_in_container_as_sandbox_user(
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
            result = _stream_stdin_to_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", script],
                tar_data,
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
            _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", script],
                check=False,
            )
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
            result = _run_in_container_as_sandbox_user(
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
            result = _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", script],
            )
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
            result = _run_in_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", cmd],
                check=False,
            )
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
        """Pushes a tar archive of ``files`` into the sandbox container.

        Docker V1 uses ``docker exec tar -x`` instead of the K8s sidecar's
        signed HTTP push — same outcome (files atomically land under
        ``mount_path``) without the keypair/HTTP plumbing.

        ``mount_path`` matches the K8s push-daemon contract: an absolute path
        inside the sandbox container (e.g. ``/workspace/managed/skills``).
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
            _stream_stdin_to_container_as_sandbox_user(
                container,
                ["/bin/sh", "-c", script],
                tar_bytes,
            )
        except ExecError as e:
            raise RuntimeError(f"write_files_to_sandbox failed: {e}") from e

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Returns an http URL the api_server can reach the sandbox on.

        api_server joins the sandbox bridge network in the compose file, so it
        can resolve the container by name on the sandbox network. If the manager
        runs outside that network, deployers can override via a
        Docker-discovered IP path in a follow-up.
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
            result = _run_in_container_as_sandbox_user(
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
            raise ValueError("Empty response from PPTX conversion.")
        if lines[0] == "ERROR_NOT_FOUND":
            raise ValueError(f"File not found: {pptx_path}")
        if lines[0] == "ERROR_NO_PDF":
            raise ValueError("soffice did not produce a PDF file.")

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
    """Adapts a ``Generator[bytes, ...]`` into a ``read(n)``-based reader.

    ``SnapshotManager.persist_snapshot_from_stream`` (and ``shutil.copyfileobj``
    under it) only need ``read(n)``. We buffer leftover bytes so the producer's
    chunk size doesn't constrain the consumer's.
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
