"""Kubernetes implementation of `SandboxIPLookup`.

Background thread watches sandbox pods and maintains a `{pod_ip:
SandboxIdentity}` cache. On any error or EOF the watch loop reconnects with
exponential backoff capped at `_RECONNECT_MAX_SECONDS`; on 410 Gone we relist.

A cache miss falls back to a one-shot read-through query by pod IP. A pod's
first requests (opencode's boot-time fetches) can beat the watch event for the
pod by a second or two; without the read-through those requests 403 as
unidentified and one-shot clients (npm's plugin-SDK install) never retry.
"""

import threading
from uuid import UUID

from kubernetes import client, watch
from kubernetes.client.rest import ApiException
from urllib3.exceptions import ProtocolError, ReadTimeoutError

from onyx.sandbox_proxy.identity import SandboxIdentity, SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.sandbox.kubernetes.k8s_client import build_core_v1_api
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.utils.logger import setup_logger

_RECONNECT_INITIAL_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_WATCH_TIMEOUT_SECONDS = 300
# Connect deadline for the long-lived watch. It must opt out of the boot client's
# short read deadline (an idle watch reads nothing for up to
# `_WATCH_TIMEOUT_SECONDS`), but a connect deadline still lets a half-open
# reconnect fail fast into the backoff loop.
_WATCH_CONNECT_TIMEOUT_S = 15.0

_SANDBOX_POD_SELECTOR = ",".join(
    [
        f"{LABEL_K8S_COMPONENT}={LABEL_K8S_COMPONENT_SANDBOX}",
        f"{LABEL_K8S_MANAGED_BY}={LABEL_K8S_MANAGED_BY_ONYX}",
    ]
)

_READTHROUGH_REQUEST_TIMEOUT: tuple[float, float] = (1.0, 2.0)
# Must exceed the leader's total request deadline, or a coalesced follower gives
# up before the leader's query completes and fails closed spuriously.
_READTHROUGH_LEADER_WAIT_SECONDS = 4.0

logger = setup_logger()


class _InflightReadThrough:
    __slots__ = ("done", "result")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: SandboxIdentity | None = None


def _identity_from_pod(pod: client.V1Pod) -> SandboxIdentity | None:
    status = pod.status
    if status is None or not status.pod_ip:
        return None

    metadata = pod.metadata
    if metadata is None:
        return None

    labels = metadata.labels or {}
    # Re-check managed-by even though the selector filters it, so loosening the
    # selector later can't enable label spoofing.
    if labels.get(LABEL_K8S_MANAGED_BY) != LABEL_K8S_MANAGED_BY_ONYX:
        return None
    sandbox_id_raw = labels.get(LABEL_SANDBOX_ID)
    tenant_id = labels.get(LABEL_TENANT_ID)
    if not sandbox_id_raw or not tenant_id:
        return None

    try:
        sandbox_id = UUID(sandbox_id_raw)
    except ValueError:
        logger.warning(
            "Skipping sandbox pod %s with non-UUID sandbox-id label %r",
            metadata.name,
            sandbox_id_raw,
        )
        return None

    return SandboxIdentity(
        sandbox_id=sandbox_id,
        tenant_id=tenant_id,
        sandbox_name=metadata.name or "",
        sandbox_ip=status.pod_ip,
    )


class K8sInformerLookup(SandboxIPLookup):
    def __init__(
        self,
        core_api: client.CoreV1Api | None = None,
        namespace: str = SANDBOX_NAMESPACE,
    ) -> None:
        if core_api is None:
            core_api = build_core_v1_api()
        self._core = core_api
        self._namespace = namespace
        self._cache: dict[str, SandboxIdentity] = {}
        self._cache_lock = threading.Lock()
        self._inflight_readthroughs: dict[str, _InflightReadThrough] = {}

        self._initial_sync_done = threading.Event()
        self._stop_event = threading.Event()
        self._synced = threading.Event()

        self._thread = threading.Thread(
            target=self._run, name="sandbox-proxy-informer", daemon=True
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
            hit = self._cache.get(src_ip)
        if hit is not None:
            return hit
        return self._read_through(src_ip)

    def _read_through(self, src_ip: str) -> SandboxIdentity | None:
        with self._cache_lock:
            hit = self._cache.get(src_ip)
            if hit is not None:
                return hit
            inflight = self._inflight_readthroughs.get(src_ip)
            is_leader = inflight is None
            if inflight is None:
                inflight = _InflightReadThrough()
                self._inflight_readthroughs[src_ip] = inflight

        if not is_leader:
            if not inflight.done.wait(timeout=_READTHROUGH_LEADER_WAIT_SECONDS):
                return None
            return inflight.result

        try:
            result = self._query_identity_by_ip(src_ip)
        finally:
            # Publish before de-registering, or a caller arriving between the pop
            # and the signal misses the entry and fires a duplicate query.
            inflight.result = result
            inflight.done.set()
            with self._cache_lock:
                self._inflight_readthroughs.pop(src_ip, None)
        return result

    def _query_identity_by_ip(self, src_ip: str) -> SandboxIdentity | None:
        try:
            listing = self._core.list_namespaced_pod(
                namespace=self._namespace,
                label_selector=_SANDBOX_POD_SELECTOR,
                field_selector=f"status.podIP={src_ip}",
                _request_timeout=_READTHROUGH_REQUEST_TIMEOUT,
            )
            identities = [
                identity
                for pod in listing.items
                if (identity := _identity_from_pod(pod)) is not None
                and identity.sandbox_ip == src_ip
            ]
        except Exception as e:
            logger.warning("identity_readthrough_error src_ip=%s error=%s", src_ip, e)
            return None

        # Require exactly one validated pod, not just one distinct sandbox_id: an
        # IP resolving to more than one pod is ambiguous regardless of labels, and
        # picking identities[0] would trust unspecified list ordering.
        if len(identities) != 1:
            if identities:
                logger.warning(
                    "identity_readthrough_ambiguous src_ip=%s sandboxes=%s",
                    src_ip,
                    [str(identity.sandbox_id) for identity in identities],
                )
            return None

        # Deliberately not cached: the watch is the sole cache writer, so a
        # read-through hit can't linger past a concurrent DELETED event and
        # misattribute a reused IP to the dead sandbox until the next relist.
        identity = identities[0]
        logger.info(
            "identity_readthrough_hit src_ip=%s sandbox=%s (watch had not caught up)",
            src_ip,
            identity.sandbox_name,
        )
        return identity

    def _run(self) -> None:
        backoff = _RECONNECT_INITIAL_SECONDS
        while not self._stop_event.is_set():
            try:
                resource_version = self._initial_list()
                self._initial_sync_done.set()
                self._synced.set()
                backoff = _RECONNECT_INITIAL_SECONDS
                self._watch_loop(resource_version)
            except ApiException as e:
                logger.warning(
                    "Informer error: %s (status=%s); reconnecting in %.1fs.",
                    e.reason,
                    e.status,
                    backoff,
                )
            except (
                ProtocolError,
                ReadTimeoutError,
                ConnectionError,
                OSError,
            ) as e:
                logger.warning(
                    "Informer connection error: %s; reconnecting in %.1fs.",
                    e,
                    backoff,
                )
            except Exception:
                logger.exception(
                    "Unexpected informer failure; reconnecting in %.1fs.",
                    backoff,
                )
            finally:
                # The K8s API server closes the watch every
                # _WATCH_TIMEOUT_SECONDS, returning the iterator cleanly. Clear
                # here so /healthz reports not-ready during the reconnect
                # window.
                self._synced.clear()

            # Wait on the stop event so shutdown is prompt.
            if self._stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    def _initial_list(self) -> str:
        listing = self._core.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=_SANDBOX_POD_SELECTOR,
        )
        new_cache: dict[str, SandboxIdentity] = {}
        for pod in listing.items:
            identity = _identity_from_pod(pod)
            if identity is None:
                continue
            existing = new_cache.get(identity.sandbox_ip)
            if existing is not None and existing.sandbox_id != identity.sandbox_id:
                # Duplicate IPs = deploy-time bug; fail loud rather than
                # route traffic with ambiguous identity.
                raise RuntimeError(
                    f"Duplicate sandbox IP {identity.sandbox_ip} mapped to {existing.sandbox_id} "
                    f"and {identity.sandbox_id}; Refusing to serve traffic with ambiguous identity."
                )
            new_cache[identity.sandbox_ip] = identity

        with self._cache_lock:
            self._cache = new_cache

        logger.info("Informer initial sync: %d sandbox pods cached.", len(new_cache))

        # Typed Optional by the client though K8s always sets it on a list.
        list_metadata = listing.metadata
        if list_metadata is None or not list_metadata.resource_version:
            raise RuntimeError(
                "K8s list response missing metadata.resource_version; cannot start incremental "
                "watch."
            )
        return list_metadata.resource_version

    def _watch_loop(self, resource_version: str) -> None:
        pod_watch = watch.Watch()
        try:
            stream = pod_watch.stream(
                self._core.list_namespaced_pod,
                namespace=self._namespace,
                label_selector=_SANDBOX_POD_SELECTOR,
                resource_version=resource_version,
                timeout_seconds=_WATCH_TIMEOUT_SECONDS,
                _request_timeout=(_WATCH_CONNECT_TIMEOUT_S, None),
            )
            for event in stream:
                if self._stop_event.is_set():
                    pod_watch.stop()
                    return
                self._apply_event(event)
        finally:
            pod_watch.stop()

    def _apply_event(self, event: dict) -> None:
        event_type = event.get("type")
        pod = event.get("object")
        if not isinstance(pod, client.V1Pod):
            return

        identity = _identity_from_pod(pod)
        pod_metadata = pod.metadata
        pod_name = pod_metadata.name if pod_metadata is not None else "<unknown>"

        if event_type == "DELETED":
            self._evict_by_pod_name(pod_name)
            return

        if identity is None:
            self._evict_by_pod_name(pod_name)
            return

        with self._cache_lock:
            # Evict any prior IP for this pod (CNI reassigns on restart).
            stale_ips = [
                cached_ip
                for cached_ip, cached_identity in self._cache.items()
                if cached_identity.sandbox_name == pod_name
                and cached_ip != identity.sandbox_ip
            ]
            for stale_ip in stale_ips:
                del self._cache[stale_ip]
            self._cache[identity.sandbox_ip] = identity

    def _evict_by_pod_name(self, pod_name: str) -> None:
        with self._cache_lock:
            stale_ips = [
                cached_ip
                for cached_ip, cached_identity in self._cache.items()
                if cached_identity.sandbox_name == pod_name
            ]
            for stale_ip in stale_ips:
                del self._cache[stale_ip]
