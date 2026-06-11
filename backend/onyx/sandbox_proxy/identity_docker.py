"""Docker-compose implementation of ``SandboxIPLookup``.

Background thread streams ``DockerClient.events()`` filtered to sandbox
containers and maintains a ``{container_ip: SandboxIdentity}`` cache. On any
error or EOF the loop reconnects with exponential backoff capped at
``_RECONNECT_MAX_SECONDS``.

Mirrors the K8s informer's posture (`identity_k8s.py`): fail loud on duplicate
IPs at initial sync, clear ``_synced`` on disconnect so ``/healthz`` flips to
503, evict by container id when the IP changes on restart.
"""

import threading
import time
from typing import Any
from uuid import UUID

from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container
from docker.types.daemon import CancellableStream
from requests.exceptions import ConnectionError as RequestsConnectionError

from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_DOCKER_NETWORK
from onyx.server.features.build.configs import SANDBOX_DOCKER_SOCKET
from onyx.server.features.build.sandbox.labels import LABEL_DOCKER_COMPONENT
from onyx.server.features.build.sandbox.labels import LABEL_DOCKER_COMPONENT_SANDBOX
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.labels import LABEL_TENANT_ID
from onyx.utils.logger import setup_logger

logger = setup_logger()

_RECONNECT_INITIAL_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _safe_close(stream: CancellableStream) -> None:
    try:
        stream.close()
    except Exception:
        logger.debug("Ignoring error closing events stream.", exc_info=True)


def _identity_from_container(
    container: Container,
    network: str,
) -> SandboxIdentity | None:
    """Builds a ``SandboxIdentity`` from a container's labels + bridge IP.

    Returns ``None`` for containers that aren't sandbox-labelled, are missing
    the sandbox/tenant labels, have a non-UUID sandbox-id, or have no IP on the
    configured sandbox bridge yet (i.e. a sandbox in a creation race that hasn't
    been attached to the network).
    """
    labels = container.labels or {}

    # Re-check the component label even though the events filter already
    # restricts to it -- belt and braces against a future filter loosen.
    if labels.get(LABEL_DOCKER_COMPONENT) != LABEL_DOCKER_COMPONENT_SANDBOX:
        return None

    sandbox_id_raw = labels.get(LABEL_SANDBOX_ID)
    tenant_id = labels.get(LABEL_TENANT_ID)
    if not sandbox_id_raw or not tenant_id:
        return None

    try:
        sandbox_id = UUID(sandbox_id_raw)
    except ValueError:
        logger.warning(
            "Skipping sandbox container %s with non-UUID sandbox-id label %r",
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
        # container_id -> ip so we can evict on `die`/`destroy` (events don't
        # carry IPs) and on restart with a new IP.
        self._by_id: dict[str, str] = {}
        self._cache_lock = threading.Lock()

        self._initial_sync_done = threading.Event()
        self._stop_event = threading.Event()
        self._synced = threading.Event()

        # Held so ``stop()`` can cancel the blocking ``for event in stream`` in
        # ``_watch_loop``. Without this, a quiescent docker daemon (no container
        # churn) leaves the iterator blocked on socket read forever and
        # ``stop()`` becomes a no-op.
        self._stream_lock = threading.Lock()
        self._stream: CancellableStream | None = None

        self._thread = threading.Thread(
            target=self._run, name="sandbox-proxy-docker-events", daemon=True
        )

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._stream_lock:
            stream = self._stream
        if stream is not None:
            # Best-effort cancel; the daemon thread tears down its own resources
            # in the ``_watch_loop`` finally block.
            _safe_close(stream)

    def wait_for_initial_sync(self, timeout_seconds: float) -> bool:
        return self._initial_sync_done.wait(timeout=timeout_seconds)

    def is_synced(self) -> bool:
        return self._synced.is_set()

    def lookup(self, src_ip: str) -> SandboxIdentity | None:
        with self._cache_lock:
            return self._cache.get(src_ip)

    def _run(self) -> None:
        backoff = _RECONNECT_INITIAL_SECONDS
        while not self._stop_event.is_set():
            try:
                # Capture ``since`` *before* the list so the events stream
                # replays any start/die that fires during the list ->
                # stream-open window. Without this the [list, stream-open] gap
                # silently drops events: a sandbox starting in that window would
                # be permanently unidentifiable until the next reconnect-driven
                # re-sync. The K8s informer uses the list response's
                # ``resource_version`` for the same guarantee. ``-1`` guards
                # against sub-second events (docker's ``since`` is
                # second-resolution). Replay overlap is safe because
                # ``_apply_event`` is idempotent.
                since_ts = int(time.time()) - 1
                self._initial_sync()
                self._initial_sync_done.set()
                self._synced.set()
                backoff = _RECONNECT_INITIAL_SECONDS
                self._watch_loop(since_ts)
            except (APIError, RequestsConnectionError, OSError) as e:
                logger.warning(
                    "Docker events lookup error: %s; reconnecting in %.1fs.",
                    e,
                    backoff,
                )
            except Exception:
                logger.exception(
                    "Unexpected docker events failure; reconnecting in %.1fs.",
                    backoff,
                )
            finally:
                # CancellableStream turns daemon-side closes into clean iterator
                # exhaustion, not an exception. Clear here so /healthz reports
                # not-ready during the reconnect window.
                self._synced.clear()

            if self._stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    def _initial_sync(self) -> None:
        containers = self._docker.containers.list(
            filters={
                "label": f"{LABEL_DOCKER_COMPONENT}={LABEL_DOCKER_COMPONENT_SANDBOX}"
            },
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
                    f"Duplicate sandbox IP {identity.sandbox_ip} mapped to "
                    f"{existing.sandbox_id} and {identity.sandbox_id}; "
                    "Refusing to serve traffic with ambiguous identity."
                )
            new_cache[identity.sandbox_ip] = identity
            new_by_id[c.id] = identity.sandbox_ip

        with self._cache_lock:
            self._cache = new_cache
            self._by_id = new_by_id

        logger.info(
            "Docker events initial sync: %d sandbox containers cached.", len(new_cache)
        )

    def _watch_loop(self, since_ts: int) -> None:
        stream = self._docker.events(
            decode=True,
            since=since_ts,
            filters={
                "type": "container",
                "label": f"{LABEL_DOCKER_COMPONENT}={LABEL_DOCKER_COMPONENT_SANDBOX}",
            },
        )
        with self._stream_lock:
            # If ``stop()`` raced us between events() returning and the
            # assignment below, close immediately -- otherwise stop() observed
            # ``self._stream is None`` and we'd block forever.
            if self._stop_event.is_set():
                _safe_close(stream)
                return
            self._stream = stream
        try:
            for event in stream:
                if self._stop_event.is_set():
                    return
                self._apply_event(event)
        finally:
            with self._stream_lock:
                self._stream = None
            _safe_close(stream)

    def _apply_event(self, event: dict[str, Any]) -> None:
        action = event.get("Action") or event.get("status")
        actor = event.get("Actor") or {}
        container_id = actor.get("ID") or event.get("id")
        if not action or not container_id:
            return

        # Container lifecycle events we care about. ``start`` lands when the
        # container is attached to its network and has an IP;
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
                # Evict any previous IP for this container (restart with a new
                # bridge IP) before upserting the new entry.
                stale_ip = self._by_id.get(container_id)
                if stale_ip is not None and stale_ip != identity.sandbox_ip:
                    self._cache.pop(stale_ip, None)

                # Evict any stale ``_by_id`` entries (different container_id)
                # that still point to the IP we are about to claim. Two distinct
                # containers cannot legitimately share a bridge IP at the same
                # instant; if our state says they do, we missed a die event for
                # the prior container. Leaving the orphan in ``_by_id`` means
                # its eventual die event would pop *this* IP from the cache via
                # the die branch's ``_cache.pop(stale_ip)``, silently
                # un-identifying the new container. Don't gate on sandbox_id --
                # a sandbox restart keeps the sandbox_id label but gets a fresh
                # container_id, and that case is what trips this most often.
                orphans = [
                    cid
                    for cid, ip in self._by_id.items()
                    if ip == identity.sandbox_ip and cid != container_id
                ]
                if orphans:
                    for cid in orphans:
                        self._by_id.pop(cid, None)
                    logger.warning(
                        "IP %s reclaimed; evicted stale by_id entries "
                        "for %s (new container=%s, sandbox_id=%s).",
                        identity.sandbox_ip,
                        orphans,
                        container_id,
                        identity.sandbox_id,
                    )

                self._cache[identity.sandbox_ip] = identity
                self._by_id[container_id] = identity.sandbox_ip
            return

        if action in ("die", "destroy", "kill", "stop"):
            with self._cache_lock:
                stale_ip = self._by_id.pop(container_id, None)
                if stale_ip is not None:
                    self._cache.pop(stale_ip, None)
            return
