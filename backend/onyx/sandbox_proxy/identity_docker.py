"""Docker-compose implementation of ``SandboxIPLookup``.

Background thread streams ``DockerClient.events()`` filtered to sandbox
containers and maintains a ``{container_ip: SandboxIdentity}`` cache.
On any error or EOF the loop reconnects with exponential backoff capped
at ``_RECONNECT_MAX_SECONDS``.

Mirrors the K8s informer's posture (`identity_k8s.py`): fail loud on
duplicate IPs at initial sync, clear ``_synced`` on disconnect so
``/healthz`` flips to 503, evict by container id when the IP changes
on restart.
"""

import threading
from typing import Any
from uuid import UUID

from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container
from requests.exceptions import ConnectionError as RequestsConnectionError

from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_DOCKER_NETWORK
from onyx.server.features.build.configs import SANDBOX_DOCKER_SOCKET
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.labels import LABEL_TENANT_ID
from onyx.utils.logger import setup_logger

logger = setup_logger()

_RECONNECT_INITIAL_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0

# Mirrors ``LABEL_COMPONENT`` / ``LABEL_COMPONENT_VALUE`` in
# ``docker_sandbox_manager.py``. Duplicated here rather than imported so
# the sandbox-proxy package doesn't pull the docker manager into its
# import graph. Keep in sync (Phase D consolidates them into labels.py).
_LABEL_COMPONENT = "onyx.app/component"
_LABEL_COMPONENT_VALUE = "craft-sandbox"


def _identity_from_container(
    container: Container,
    network: str,
) -> SandboxIdentity | None:
    """Build a ``SandboxIdentity`` from a container's labels + bridge IP.

    Returns ``None`` for containers that aren't sandbox-labelled, are
    missing the sandbox/tenant labels, have a non-UUID sandbox-id, or
    have no IP on the configured sandbox bridge yet (i.e. a sandbox in
    a creation race that hasn't been attached to the network).
    """
    labels = container.labels or {}

    # Re-check the component label even though the events filter already
    # restricts to it -- belt and braces against a future filter loosen.
    if labels.get(_LABEL_COMPONENT) != _LABEL_COMPONENT_VALUE:
        return None

    sandbox_id_raw = labels.get(LABEL_SANDBOX_ID)
    tenant_id = labels.get(LABEL_TENANT_ID)
    if not sandbox_id_raw or not tenant_id:
        return None

    try:
        sandbox_id = UUID(sandbox_id_raw)
    except ValueError:
        logger.warning(
            "skipping sandbox container %s with non-UUID sandbox-id label %r",
            container.name,
            sandbox_id_raw,
        )
        return None

    networks = ((container.attrs or {}).get("NetworkSettings") or {}).get(
        "Networks"
    ) or {}
    bridge = networks.get(network) or {}
    ip = bridge.get("IPAddress")
    if not ip:
        return None

    return SandboxIdentity(
        sandbox_id=sandbox_id,
        tenant_id=tenant_id,
        sandbox_name=container.name or "",
        sandbox_ip=ip,
    )


class DockerEventsLookup(SandboxIPLookup):
    """Docker-events-driven IP -> identity lookup for compose deployments."""

    def __init__(
        self,
        docker_client: DockerClient | None = None,
        network: str = SANDBOX_DOCKER_NETWORK,
    ) -> None:
        if docker_client is None:
            docker_client = DockerClient(base_url=f"unix://{SANDBOX_DOCKER_SOCKET}")
        self._docker = docker_client
        self._network = network

        self._cache: dict[str, SandboxIdentity] = {}
        # container_id -> ip so we can evict on `die`/`destroy` (events
        # don't carry IPs) and on restart with a new IP.
        self._by_id: dict[str, str] = {}
        self._cache_lock = threading.Lock()

        self._initial_sync_done = threading.Event()
        self._stop_event = threading.Event()
        self._synced = threading.Event()

        self._thread = threading.Thread(
            target=self._run, name="sandbox-proxy-docker-events", daemon=True
        )

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def wait_for_initial_sync(self, timeout_seconds: float) -> bool:
        return self._initial_sync_done.wait(timeout=timeout_seconds)

    def is_synced(self) -> bool:
        return self._synced.is_set()

    def lookup(self, src_ip: str) -> SandboxIdentity | None:
        with self._cache_lock:
            return self._cache.get(src_ip)

    # ------------------------------------------------------------------
    # background loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        backoff = _RECONNECT_INITIAL_SECONDS
        while not self._stop_event.is_set():
            try:
                self._initial_sync()
                self._initial_sync_done.set()
                self._synced.set()
                backoff = _RECONNECT_INITIAL_SECONDS
                self._watch_loop()
            except (APIError, RequestsConnectionError, OSError) as e:
                logger.warning(
                    "docker events lookup error: %s; reconnecting in %.1fs",
                    e,
                    backoff,
                )
            except Exception:
                logger.exception(
                    "unexpected docker events failure; reconnecting in %.1fs",
                    backoff,
                )
            finally:
                # Clear after every iteration -- including clean returns
                # from _watch_loop. CancellableStream converts every
                # daemon-side close (EOF, restart, network hiccup) to
                # StopIteration, so the for-loop exhausts cleanly and we
                # return without raising. Without this clear, /healthz
                # would lie during the reconnect backoff window: we are
                # no longer actively watching events but _synced is
                # still set from the prior iteration.
                self._synced.clear()

            if self._stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    def _initial_sync(self) -> None:
        containers = self._docker.containers.list(
            filters={"label": f"{_LABEL_COMPONENT}={_LABEL_COMPONENT_VALUE}"},
        )
        new_cache: dict[str, SandboxIdentity] = {}
        new_by_id: dict[str, str] = {}
        for c in containers:
            # ``containers.list`` returns objects with attrs already populated;
            # reload defensively in case the SDK ever changes that.
            try:
                c.reload()
            except (APIError, NotFound):
                continue
            identity = _identity_from_container(c, self._network)
            if identity is None:
                continue
            existing = new_cache.get(identity.sandbox_ip)
            if existing is not None and existing.sandbox_id != identity.sandbox_id:
                raise RuntimeError(
                    f"duplicate sandbox IP {identity.sandbox_ip} mapped to "
                    f"{existing.sandbox_id} and {identity.sandbox_id}; "
                    "refusing to serve traffic with ambiguous identity"
                )
            new_cache[identity.sandbox_ip] = identity
            new_by_id[c.id] = identity.sandbox_ip

        with self._cache_lock:
            self._cache = new_cache
            self._by_id = new_by_id

        logger.info(
            "docker events initial sync: %d sandbox containers cached", len(new_cache)
        )

    def _watch_loop(self) -> None:
        stream = self._docker.events(
            decode=True,
            filters={
                "type": "container",
                "label": f"{_LABEL_COMPONENT}={_LABEL_COMPONENT_VALUE}",
            },
        )
        try:
            for event in stream:
                if self._stop_event.is_set():
                    return
                self._apply_event(event)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _apply_event(self, event: dict[str, Any]) -> None:
        action = event.get("Action") or event.get("status")
        actor = event.get("Actor") or {}
        container_id = actor.get("ID") or event.get("id")
        if not action or not container_id:
            return

        # Container lifecycle events we care about. ``start`` lands when
        # the container is attached to its network and has an IP;
        # ``die``/``destroy``/``kill`` mean the IP is going away.
        if action == "start":
            try:
                container = self._docker.containers.get(container_id)
            except (NotFound, APIError):
                return
            identity = _identity_from_container(container, self._network)
            if identity is None:
                return
            with self._cache_lock:
                # Evict any previous IP for this container (restart with
                # a new bridge IP) before upserting the new entry.
                stale_ip = self._by_id.get(container_id)
                if stale_ip is not None and stale_ip != identity.sandbox_ip:
                    self._cache.pop(stale_ip, None)
                self._cache[identity.sandbox_ip] = identity
                self._by_id[container_id] = identity.sandbox_ip
            return

        if action in ("die", "destroy", "kill", "stop"):
            with self._cache_lock:
                stale_ip = self._by_id.pop(container_id, None)
                if stale_ip is not None:
                    self._cache.pop(stale_ip, None)
            return
