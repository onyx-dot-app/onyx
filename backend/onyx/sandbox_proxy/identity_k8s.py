"""Kubernetes implementation of `SandboxIPLookup`.

Background thread watches sandbox pods and maintains a `{pod_ip:
SandboxIdentity}` cache. On any error or EOF the watch loop reconnects with
exponential backoff capped at `_RECONNECT_MAX_SECONDS`; on 410 Gone we relist.
"""

import threading
from uuid import UUID

from kubernetes import client
from kubernetes import watch
from kubernetes.client.rest import ApiException
from urllib3.exceptions import ProtocolError
from urllib3.exceptions import ReadTimeoutError

from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.sandbox.kubernetes.k8s_client import load_kube_config
from onyx.server.features.build.sandbox.labels import LABEL_K8S_COMPONENT
from onyx.server.features.build.sandbox.labels import LABEL_K8S_COMPONENT_SANDBOX
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY_ONYX
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.labels import LABEL_TENANT_ID
from onyx.utils.logger import setup_logger

_RECONNECT_INITIAL_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_WATCH_TIMEOUT_SECONDS = 300

_SANDBOX_POD_SELECTOR = ",".join(
    [
        f"{LABEL_K8S_COMPONENT}={LABEL_K8S_COMPONENT_SANDBOX}",
        f"{LABEL_K8S_MANAGED_BY}={LABEL_K8S_MANAGED_BY_ONYX}",
    ]
)

logger = setup_logger()


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
            load_kube_config()
            core_api = client.CoreV1Api()
        self._core = core_api
        self._namespace = namespace
        self._cache: dict[str, SandboxIdentity] = {}
        self._cache_lock = threading.Lock()

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
            return self._cache.get(src_ip)

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
