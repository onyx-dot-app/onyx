"""Harness sandboxes as Docker containers (Compose, `SANDBOX_BACKEND=docker`).

The container joins the sandbox bridge (`onyx_craft_sandbox`). Its
entrypoint is `firewall-init` (entrypoint mode): it installs the proxy CA
and the iptables lockdown as root, then drops to UID 1000 with no
capabilities and starts `sandbox-entrypoint` (the guest daemon). The
daemon's key and TLS files go into the created container before it starts.
The api_server dials `<name>:<port>` on the bridge, or, with
`publish_daemon_port` (host-run dev and tests), a port on 127.0.0.1.
"""

import io
import tarfile
import threading
import time
from datetime import UTC, datetime
from typing import Any

from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from pydantic import TypeAdapter

from onyx.configs.app_configs import DEV_MODE
from onyx.server.features.build.configs import (
    SANDBOX_DOCKER_CPU_LIMIT,
    SANDBOX_DOCKER_MEMORY_LIMIT,
    SANDBOX_DOCKER_NETWORK,
    SANDBOX_DOCKER_PIDS_LIMIT,
    SANDBOX_DOCKER_RUNTIME,
    SANDBOX_DOCKER_SOCKET,
    SANDBOX_HARNESS_DAEMON_PORT,
    SANDBOX_HARNESS_IMAGE,
    SANDBOX_PROXY_CA_VOLUME_NAME,
    SANDBOX_PROXY_HOST,
)
from onyx.server.features.build.sandbox.container.models import (
    ContainerRuntimeKind,
    ContainerSpec,
    ContainerState,
    DaemonCredentials,
    RuntimeContainer,
)
from onyx.server.features.build.sandbox.container.runtime import (
    DAEMON_CERT_FILE,
    DAEMON_FILES_DIR,
    DAEMON_KEY_FILE,
    DAEMON_PRIVATE_KEY_FILE,
    ContainerRuntime,
    daemon_args,
    harness_labels,
    parse_labels,
)
from onyx.server.features.build.sandbox.docker.containers import (
    PROXY_CA_SOURCE_DIR,
    DockerSandboxOps,
    build_sandbox_labels,
    detect_compose_project,
    proxy_env_vars,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_DOCKER_NETWORK,
    LABEL_SANDBOX_KIND,
    SANDBOX_KIND_HARNESS,
)
from onyx.server.features.build.sandbox.models import SandboxResourceKind
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ENTRYPOINT = "/usr/local/bin/firewall-init"
_DAEMON_ENTRYPOINT = "/usr/local/bin/sandbox-entrypoint"
# firewall-init: NET_ADMIN for iptables, SETPCAP for the bounding-set drop,
# SETUID/SETGID for setpriv, CHOWN for its mount-point repair. All leave the
# bounding set before the daemon starts.
_INIT_CAPABILITIES = ["NET_ADMIN", "SETPCAP", "SETUID", "SETGID", "CHOWN"]
_TMPFS_OPTIONS = "rw,nosuid,nodev,size=5g,mode=1777"
# Chrome needs more shared memory than Docker's 64 MiB.
_SHM_SIZE = "1g"
_SANDBOX_UID = 1000
# Docker states that never serve again (a restarting container may).
_FAILED_STATES = frozenset({"exited", "dead", "removing"})
_POLL_SECONDS = 0.25
_TIMESTAMP = TypeAdapter(datetime)


def _daemon_files_tar(credentials: DaemonCredentials) -> bytes:
    """The daemon's files under DAEMON_FILES_DIR: the directory is root's,
    the key and the TLS key are readable by the sandbox user only."""
    buffer = io.BytesIO()
    root = DAEMON_FILES_DIR.lstrip("/")
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        parts = root.split("/")
        for depth in range(1, len(parts) + 1):
            info = tarfile.TarInfo("/".join(parts[:depth]))
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(info)
        for name, data, mode in (
            (DAEMON_KEY_FILE, credentials.key.get_secret_value(), 0o400),
            (DAEMON_CERT_FILE, credentials.cert_pem, 0o444),
            (
                DAEMON_PRIVATE_KEY_FILE,
                credentials.private_key_pem.get_secret_value(),
                0o400,
            ),
        ):
            raw = data.encode()
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(raw)
            info.mode = mode
            info.uid = info.gid = _SANDBOX_UID
            tar.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def build_harness_container_kwargs(
    spec: ContainerSpec,
    *,
    image: str,
    network: str,
    proxy_host: str,
    proxy_ca_volume: str,
    memory_limit: str,
    cpu_limit: float,
    pids_limit: int,
    oci_runtime: str,
    publish_daemon_port: bool,
    compose_project: str | None,
    daemon_port: int = SANDBOX_HARNESS_DAEMON_PORT,
) -> dict[str, Any]:
    """`DockerClient.containers.create` arguments of one harness container,
    with the Craft container's security posture."""
    labels = {
        **build_sandbox_labels(
            spec.sandbox_id,
            spec.tenant_id,
            None,
            compose_project=compose_project,
            provisioning_attempt_number=spec.attempt,
        ),
        **harness_labels(spec),
        LABEL_DOCKER_NETWORK: network,
    }
    kwargs: dict[str, Any] = {
        "name": spec.name,
        "image": image,
        "entrypoint": [_ENTRYPOINT],
        "command": [_DAEMON_ENTRYPOINT, *daemon_args(daemon_port)],
        "labels": labels,
        # firewall-init starts as root and drops to UID 1000 itself.
        "user": "0:0",
        "cap_drop": ["ALL"],
        "cap_add": list(_INIT_CAPABILITIES),
        "security_opt": ["no-new-privileges:true"],
        "privileged": False,
        "read_only": False,
        "network": network,
        "environment": proxy_env_vars(sandbox_proxy_host=proxy_host),
        "volumes": {proxy_ca_volume: {"bind": PROXY_CA_SOURCE_DIR, "mode": "ro"}},
        "tmpfs": {"/tmp": _TMPFS_OPTIONS},  # noqa: S108 - the sandbox's /tmp.
        "shm_size": _SHM_SIZE,
        "mem_limit": memory_limit,
        "nano_cpus": int(cpu_limit * 1_000_000_000),
        "pids_limit": pids_limit,
        # A daemon that exits restarts with its container; calls on its old
        # executions then end (ExecSessionEndedError).
        "restart_policy": {"Name": "unless-stopped"},
    }
    if oci_runtime:
        kwargs["runtime"] = oci_runtime
    if publish_daemon_port:
        kwargs["ports"] = {f"{daemon_port}/tcp": ("127.0.0.1", None)}
    return kwargs


class DockerRuntime(DockerSandboxOps, ContainerRuntime):
    kind = ContainerRuntimeKind.DOCKER

    def __init__(
        self,
        *,
        docker_client: DockerClient | None = None,
        image: str = SANDBOX_HARNESS_IMAGE,
        network: str = SANDBOX_DOCKER_NETWORK,
        proxy_host: str = SANDBOX_PROXY_HOST,
        proxy_ca_volume: str = SANDBOX_PROXY_CA_VOLUME_NAME,
        publish_daemon_port: bool = DEV_MODE,
        daemon_port: int = SANDBOX_HARNESS_DAEMON_PORT,
    ) -> None:
        if not proxy_host:
            raise RuntimeError(
                "Container harness sandboxes on Docker need SANDBOX_PROXY_HOST: "
                "the egress proxy is their only way out."
            )
        self._docker = docker_client or DockerClient(
            base_url=f"unix://{SANDBOX_DOCKER_SOCKET}"
        )
        self._cleanup_docker = self._docker
        self._image = image
        self._image_checked = False
        self._image_check_lock = threading.Lock()
        self._network_name = network
        self._compose_project = detect_compose_project(self._docker)
        self._proxy_host = proxy_host
        self._proxy_ca_volume = proxy_ca_volume
        self._publish = publish_daemon_port
        self._port = daemon_port

    def create(
        self, spec: ContainerSpec, credentials: DaemonCredentials, deadline: float
    ) -> str:
        # A cold pull can take minutes; it does not count against the start.
        pull_started = time.monotonic()
        self._ensure_sandbox_image()
        deadline += time.monotonic() - pull_started
        self._ensure_sandbox_network()
        kwargs = build_harness_container_kwargs(
            spec,
            image=self._image,
            network=self._network_name,
            proxy_host=self._proxy_host,
            proxy_ca_volume=self._proxy_ca_volume,
            memory_limit=SANDBOX_DOCKER_MEMORY_LIMIT,
            cpu_limit=SANDBOX_DOCKER_CPU_LIMIT,
            pids_limit=SANDBOX_DOCKER_PIDS_LIMIT,
            oci_runtime=SANDBOX_DOCKER_RUNTIME,
            publish_daemon_port=self._publish,
            compose_project=self._compose_project,
            daemon_port=self._port,
        )
        container: Container = self._docker.containers.create(**kwargs)
        try:
            if not container.put_archive("/", _daemon_files_tar(credentials)):
                raise RuntimeError(f"could not write the daemon files of {spec.name}")
            container.start()
            if not self._wait_for_container_running(container, deadline):
                raise TimeoutError(f"sandbox container {spec.name} did not start")
            address = self._address(container, deadline)
        except BaseException:
            self._remove_incomplete_container(container)
            raise
        logger.info("sandbox_container_created name=%s", spec.name)
        return address

    def _address(self, container: Container, deadline: float) -> str:
        if not self._publish:
            return f"{container.name}:{self._port}"
        while True:
            container.reload()
            ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
            for binding in ports.get(f"{self._port}/tcp") or []:
                if binding.get("HostPort"):
                    return f"127.0.0.1:{binding['HostPort']}"
            if time.monotonic() >= deadline:
                raise TimeoutError(f"no published daemon port on {container.name}")
            time.sleep(_POLL_SECONDS)

    def _runtime_container(self, container: Container) -> RuntimeContainer:
        attrs = container.attrs or {}
        status = (attrs.get("State") or {}).get("Status", "")
        tenant_id, sandbox_id, attempt = parse_labels(container.labels or {})
        address: str | None
        try:
            address = self._address(container, deadline=0.0)
        except TimeoutError:
            address = None
        return RuntimeContainer(
            name=container.name or "",
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            attempt=attempt,
            state=ContainerState.FAILED
            if status in _FAILED_STATES
            else ContainerState.RUNNING,
            address=address,
            created_at=_TIMESTAMP.validate_python(attrs["Created"])
            if attrs.get("Created")
            else datetime.now(UTC),
        )

    def inspect(self, name: str) -> RuntimeContainer | None:
        try:
            container = self._docker.containers.get(name)
        except NotFound:
            return None
        if (container.labels or {}).get(LABEL_SANDBOX_KIND) != SANDBOX_KIND_HARNESS:
            return None
        return self._runtime_container(container)

    def delete(self, name: str) -> None:
        try:
            container = self._docker.containers.get(name)
            if (container.labels or {}).get(LABEL_SANDBOX_KIND) != SANDBOX_KIND_HARNESS:
                raise RuntimeError(f"{name} is not a harness sandbox container")
            container.remove(force=True)
        except NotFound:
            return
        except APIError as e:
            if e.status_code == 404:
                return
            raise
        logger.info("sandbox_container_deleted name=%s", name)

    def list_containers(self, deadline: float) -> list[RuntimeContainer]:
        found: list[RuntimeContainer] = []
        for item in self._iter_owned_items(
            [f"{LABEL_SANDBOX_KIND}={SANDBOX_KIND_HARNESS}"], deadline
        ):
            if item.kind is not SandboxResourceKind.CONTAINER:
                continue
            try:
                container = self._docker.containers.get(item.instance_id)
            except NotFound:
                continue
            found.append(self._runtime_container(container))
        return found
