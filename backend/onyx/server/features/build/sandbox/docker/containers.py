"""Docker steps shared by the sandbox container backends.

The Craft ``DockerSandboxManager`` and the harness Docker runtime both label,
harden, and clean up sandbox containers through these helpers. The mixin
methods dispatch through ``self`` so a backend can override one step.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from threading import Lock
from typing import NamedTuple
from uuid import UUID

from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from onyx.server.features.build.configs import (
    SANDBOX_DOCKER_NETWORK,
    SANDBOX_PROXY_INJECTED_PLACEHOLDER,
    SANDBOX_PROXY_PORT,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_DOCKER_NETWORK,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_PROVISIONING_ATTEMPT,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.models import SandboxResourceKind
from onyx.server.features.build.sandbox.resources import remaining_request_timeout
from onyx.server.features.build.timeouts import POLL_INTERVAL_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


LABEL_COMPONENT = "onyx.app/component"
LABEL_COMPONENT_VALUE = "craft-sandbox"
LABEL_USER_ID = "onyx.app/user-id"

# Egress proxy file paths inside the sandbox container. Matched by
# ``firewall-init.sh``: ``CA_SRC`` defaults to ``/sandbox-ca/ca.crt`` and
# ``CA_DST`` to ``/etc/ssl/sandbox/ca-bundle.crt``. The bundle dir lives in the
# container's writable layer (not a separate volume) since only the init step
# writes to it and only the agent reads it.
PROXY_CA_SOURCE_DIR = "/sandbox-ca"
_PROXY_CA_BUNDLE_DIR = "/etc/ssl/sandbox"
PROXY_CA_BUNDLE_FILE = f"{_PROXY_CA_BUNDLE_DIR}/ca-bundle.crt"

_MUTABLE_SANDBOX_IMAGE_TAGS = {"latest", "beta", "edge"}

_COMPOSE_INTERNAL_HOSTNAMES = {
    "api_server",
    "background",
    "relational_db",
    "cache",
    "minio",
    "object-store",
    "model_server",
    "indexing_model_server",
    "inference_model_server",
    "web_server",
    "opensearch",
}


def looks_like_internal_compose_host(url: str) -> bool:
    """Heuristic: Does ``url`` reference a compose-internal service hostname?

    Used to warn deployers that pointed ONYX_SERVER_URL at a service available
    only on Compose's default network. Sandboxes can resolve the dedicated
    ``onyx-craft-api`` alias, but not these unrelated service names.
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


def detect_compose_project(docker_client: DockerClient) -> str | None:
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
    provisioning_attempt_number: int | None = None,
) -> dict[str, str]:
    """Standard label set for sandbox-owned docker resources.

    ``compose_project`` is added as ``com.docker.compose.project`` so Docker
    Desktop groups sandbox containers under the same "onyx" stack header as
    api_server/postgres/redis/etc. Auto-detected by ``DockerSandboxManager``
    from its own container's labels.

    ``provisioning_attempt_number`` is stamped on containers (not the per-sandbox
    volume, which persists across generations) for attribution.
    """
    labels: dict[str, str] = {
        LABEL_DOCKER_NETWORK: SANDBOX_DOCKER_NETWORK,
        LABEL_COMPONENT: LABEL_COMPONENT_VALUE,
        LABEL_SANDBOX_ID: str(sandbox_id),
        LABEL_TENANT_ID: tenant_id,
        LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
    }
    if user_id is not None:
        labels[LABEL_USER_ID] = str(user_id)
    if compose_project:
        labels["com.docker.compose.project"] = compose_project
    if provisioning_attempt_number is not None:
        labels[LABEL_PROVISIONING_ATTEMPT] = str(provisioning_attempt_number)
    return labels


# Sandbox should reach loopback directly; everything else (api server included)
# goes through the proxy.
IPV4_LISTEN_HOST = "0.0.0.0"  # noqa: S104 — isolated sandbox bridge listener
# Node needs the bracketed "[::1]" form to bypass the proxy for IPv6 loopback.
_NO_PROXY_LIST = "127.0.0.1,localhost,::1,[::1]"


def proxy_env_vars(
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
        "SANDBOX_PROXY_CA_BUNDLE_SRC": f"{PROXY_CA_SOURCE_DIR}/ca.crt",
        "SANDBOX_PROXY_CA_BUNDLE_DST": PROXY_CA_BUNDLE_FILE,
        # Agent-side proxy + CA wiring.
        "HTTPS_PROXY": proxy_url,
        "HTTP_PROXY": proxy_url,
        "https_proxy": proxy_url,
        "http_proxy": proxy_url,
        "NO_PROXY": _NO_PROXY_LIST,
        "no_proxy": _NO_PROXY_LIST,
        # Node's built-in fetch ignores HTTPS_PROXY without this.
        "NODE_USE_ENV_PROXY": "1",
        # SDK-specific CA env vars for libs that bypass /etc/ssl/certs.
        "NODE_EXTRA_CA_CERTS": PROXY_CA_BUNDLE_FILE,
        "REQUESTS_CA_BUNDLE": PROXY_CA_BUNDLE_FILE,
        "SSL_CERT_FILE": PROXY_CA_BUNDLE_FILE,
        "AWS_CA_BUNDLE": PROXY_CA_BUNDLE_FILE,
        "CURL_CA_BUNDLE": PROXY_CA_BUNDLE_FILE,
        "GIT_SSL_CAINFO": PROXY_CA_BUNDLE_FILE,
        "GH_TOKEN": SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        "GH_NO_UPDATE_NOTIFIER": "1",
    }


class OwnedDockerItem(NamedTuple):
    """A sandbox container or volume whose deployment ownership was verified."""

    kind: SandboxResourceKind
    name: str
    instance_id: str
    created_at: str
    labels: dict[str, str]


class DockerSandboxOps:
    """Container lifecycle steps. Subclasses set ``_docker``,
    ``_cleanup_docker``, ``_image``, ``_image_checked``, ``_image_check_lock``,
    ``_network_name`` and ``_compose_project``."""

    _docker: DockerClient
    _cleanup_docker: DockerClient
    _image: str
    _image_checked: bool
    _image_check_lock: Lock
    _network_name: str
    _compose_project: str | None

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

    def _wait_for_container_running(
        self, container: Container, deadline: float
    ) -> bool:
        while time.monotonic() < deadline:
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
            time.sleep(POLL_INTERVAL_SECONDS)
        return False

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

    def _iter_owned_items(
        self, extra_labels: list[str], deadline: float
    ) -> Iterator[OwnedDockerItem]:
        """Yield this deployment's sandbox containers, then volumes, with labels."""
        filters: dict[str, str | list[str] | bool] = {
            "label": [
                f"{LABEL_COMPONENT}={LABEL_COMPONENT_VALUE}",
                f"{LABEL_K8S_MANAGED_BY}={LABEL_K8S_MANAGED_BY_ONYX}",
                *extra_labels,
            ]
        }
        verified_volumes: dict[str, str] = {}
        for kind in (
            SandboxResourceKind.CONTAINER,
            SandboxResourceKind.VOLUME,
        ):
            remaining_request_timeout(deadline)
            items = (
                self._cleanup_docker.containers.list(all=True, filters=filters)
                if kind == SandboxResourceKind.CONTAINER
                else self._cleanup_docker.volumes.list(filters=filters)
            )
            remaining_request_timeout(deadline)
            for item in items:
                remaining_request_timeout(deadline)
                labels = (
                    item.attrs.get("Labels")
                    if kind == SandboxResourceKind.VOLUME
                    else item.labels
                )
                labels = labels or {}
                resource_network = labels.get(LABEL_DOCKER_NETWORK)
                if (
                    resource_network is not None
                    and resource_network != self._network_name
                ):
                    continue
                if resource_network is None:
                    project_matches = (
                        bool(self._compose_project)
                        and labels.get("com.docker.compose.project")
                        == self._compose_project
                    )
                    network_matches = (
                        kind == SandboxResourceKind.CONTAINER
                        and self._network_name
                        in (item.attrs.get("NetworkSettings", {}).get("Networks") or {})
                    )
                    volume_matches = kind == SandboxResourceKind.VOLUME and (
                        verified_volumes.get(item.name) == labels.get(LABEL_SANDBOX_ID)
                    )
                    if not (project_matches or network_matches or volume_matches):
                        logger.warning(
                            "Retaining Docker resource %s without verified deployment ownership",
                            item.name,
                        )
                        continue
                sandbox_label = labels.get(LABEL_SANDBOX_ID)
                if kind == SandboxResourceKind.CONTAINER and sandbox_label:
                    for mount in item.attrs.get("Mounts") or []:
                        if mount.get("Type") == "volume" and mount.get("Name"):
                            verified_volumes[mount["Name"]] = sandbox_label
                yield OwnedDockerItem(
                    kind=kind,
                    name=item.name,
                    instance_id=item.id
                    if kind == SandboxResourceKind.CONTAINER
                    else item.attrs["CreatedAt"],
                    created_at=item.attrs["Created"]
                    if kind == SandboxResourceKind.CONTAINER
                    else item.attrs["CreatedAt"],
                    labels=labels,
                )
