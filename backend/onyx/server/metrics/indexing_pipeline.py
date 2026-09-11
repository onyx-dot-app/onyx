"""Prometheus collectors for Celery queue depths and infrastructure health.

The concrete collectors here run in the monitoring celery worker, registered by
indexing_pipeline_setup.py. ``_CachedCollector`` is also the base of the API
server's license collector, so it must behave under both the worker's
thread-per-request WSGI server and the API server's request threadpool.

Results are cached for a configurable TTL (default 30s) so a 15s scrape cadence
does not hammer Redis. Dashboards tolerate that staleness.

Note: connector health and index attempt metrics are push-based (emitted by
workers at state-change time) and live in connector_health_metrics.py.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from typing import Any

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from redis import Redis

from onyx.background.celery.celery_redis import (
    celery_get_broker_client,
    celery_get_queue_length,
    celery_get_unacked_task_ids,
)
from onyx.configs.constants import OnyxCeleryQueues
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Default cache TTL in seconds. Scrapes hitting within this window return
# the previous result without re-querying Redis/Postgres.
_DEFAULT_CACHE_TTL = 30.0

# Seconds the scrape that starts a collection waits before returning the stale
# cache. Under Prometheus's default 10s scrape timeout, so no thread outlives the
# scrape it serves. The collection keeps running and is banked when it lands.
_DEFAULT_COLLECT_TIMEOUT = 8.0

# Seconds between "still running" warnings for a wedged collection, so the log
# holds one line per window rather than one per scrape.
_STALL_WARNING_INTERVAL = 120.0

_QUEUE_LABEL_MAP: dict[str, str] = {
    OnyxCeleryQueues.PRIMARY: "primary",
    OnyxCeleryQueues.DOCPROCESSING: "docprocessing",
    OnyxCeleryQueues.CONNECTOR_DOC_FETCHING: "docfetching",
    OnyxCeleryQueues.VESPA_METADATA_SYNC: "vespa_metadata_sync",
    OnyxCeleryQueues.CONNECTOR_DELETION: "connector_deletion",
    OnyxCeleryQueues.CONNECTOR_PRUNING: "connector_pruning",
    OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC: "permissions_sync",
    OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC: "external_group_sync",
    OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT: "permissions_upsert",
    OnyxCeleryQueues.CONNECTOR_HIERARCHY_FETCHING: "hierarchy_fetching",
    OnyxCeleryQueues.LLM_MODEL_UPDATE: "llm_model_update",
    OnyxCeleryQueues.CHECKPOINT_CLEANUP: "checkpoint_cleanup",
    OnyxCeleryQueues.INDEX_ATTEMPT_CLEANUP: "index_attempt_cleanup",
    OnyxCeleryQueues.CSV_GENERATION: "csv_generation",
    OnyxCeleryQueues.CAPABILITY_CHECKS: "capability_checks",
    OnyxCeleryQueues.USER_FILE_PROCESSING: "user_file_processing",
    OnyxCeleryQueues.USER_FILE_PROJECT_SYNC: "user_file_project_sync",
    OnyxCeleryQueues.USER_FILE_DELETE: "user_file_delete",
    OnyxCeleryQueues.MONITORING: "monitoring",
    OnyxCeleryQueues.SANDBOX: "sandbox",
    OnyxCeleryQueues.OPENSEARCH_MIGRATION: "opensearch_migration",
}

# Queues where prefetched (unacked) task counts are meaningful
_UNACKED_QUEUES: list[str] = [
    OnyxCeleryQueues.CONNECTOR_DOC_FETCHING,
    OnyxCeleryQueues.DOCPROCESSING,
]


class _CachedCollector(Collector):
    """Base collector with a TTL cache and bounded waiting.

    Subclasses implement ``_collect_fresh()``. Inside the TTL ``collect()`` returns
    the cache. Past it, the scrape that finds no collection running starts one and
    waits at most ``collect_timeout``. Every other scrape returns the cache (or
    nothing) at once, so a stalled query pins one request thread, not one per
    scrape. A collection that never returns keeps the single executor worker and
    leaves the collector on stale data, so ``_collect_fresh`` must rely on its own
    I/O deadlines.
    """

    def __init__(
        self,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        collect_timeout: float = _DEFAULT_COLLECT_TIMEOUT,
    ) -> None:
        self._cache_ttl = cache_ttl
        self._collect_timeout = collect_timeout
        self._cached_result: list[GaugeMetricFamily] | None = None
        self._last_collect_time: float = 0.0
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=type(self).__name__,
        )
        self._inflight: concurrent.futures.Future[list[GaugeMetricFamily]] | None = None
        self._inflight_started: float = 0.0
        self._last_stall_log: float = 0.0

    def collect(self) -> list[GaugeMetricFamily]:
        with self._lock:
            self._absorb_finished_locked()
            now = time.monotonic()
            if (
                self._cached_result is not None
                and now - self._last_collect_time < self._cache_ttl
            ):
                return self._cached_result
            if self._inflight is not None:
                self._log_stall_locked(now)
                return self._cached_or_empty()
            future = self._executor.submit(self._collect_fresh)
            self._inflight = future
            self._inflight_started = now

        # Wait outside the lock so a slow collection blocks only its starter.
        try:
            result = future.result(timeout=self._collect_timeout)
        except Exception:
            # A collection may itself raise TimeoutError, so the future's state,
            # not the exception type, tells a stalled wait from a failed run.
            if not future.done():
                logger.warning(
                    "%s._collect_fresh() timed out after %ss, returning stale cache",
                    type(self).__name__,
                    self._collect_timeout,
                )
                # This line opens the throttle window for the stall warnings.
                with self._lock:
                    self._last_stall_log = time.monotonic()
                return self._cached_or_empty()
            logger.exception("Error in %s._collect_fresh()", type(self).__name__)
            with self._lock:
                if self._inflight is future:
                    self._inflight = None
            # Stale cache beats nothing: metrics should not vanish on a blip.
            return self._cached_or_empty()

        with self._lock:
            if self._inflight is future:
                self._inflight = None
            self._store_locked(result, now)
        return result

    def _cached_or_empty(self) -> list[GaugeMetricFamily]:
        return self._cached_result if self._cached_result is not None else []

    def _store_locked(self, result: list[GaugeMetricFamily], started: float) -> None:
        # A result is stamped with its start time, so a slow one that lands
        # after a newer collection cannot replace it.
        if started < self._last_collect_time:
            return
        self._cached_result = result
        self._last_collect_time = started

    def _absorb_finished_locked(self) -> None:
        """Bank a collection that finished after its starter stopped waiting."""
        future, started = self._inflight, self._inflight_started
        if future is None or not future.done():
            return
        self._inflight = None
        try:
            result = future.result()
        except Exception:
            logger.exception("Error in %s._collect_fresh()", type(self).__name__)
            return
        self._store_locked(result, started)

    def _log_stall_locked(self, now: float) -> None:
        running_for = now - self._inflight_started
        if running_for < self._collect_timeout:
            return
        if now - self._last_stall_log < _STALL_WARNING_INTERVAL:
            return
        self._last_stall_log = now
        logger.warning(
            "%s._collect_fresh() still running after %.0fs, returning stale cache",
            type(self).__name__,
            running_for,
        )

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        raise NotImplementedError

    def describe(self) -> list[GaugeMetricFamily]:
        return []


class QueueDepthCollector(_CachedCollector):
    """Reads Celery queue lengths from the broker Redis on each scrape."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._celery_app: Any | None = None

    def set_celery_app(self, app: Any) -> None:
        """Set the Celery app for broker Redis access."""
        self._celery_app = app

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._celery_app is None:
            return []

        redis_client = celery_get_broker_client(self._celery_app)

        depth = GaugeMetricFamily(
            "onyx_queue_depth",
            "Number of tasks waiting in Celery queue",
            labels=["queue"],
        )
        unacked = GaugeMetricFamily(
            "onyx_queue_unacked",
            "Number of prefetched (unacked) tasks for queue",
            labels=["queue"],
        )
        queue_age = GaugeMetricFamily(
            "onyx_queue_oldest_task_age_seconds",
            "Age of the oldest task in the queue (seconds since enqueue)",
            labels=["queue"],
        )

        now = time.time()

        for queue_name, label in _QUEUE_LABEL_MAP.items():
            length = celery_get_queue_length(queue_name, redis_client)
            depth.add_metric([label], length)

            # Peek at the oldest message to get its age
            if length > 0:
                age = self._get_oldest_message_age(redis_client, queue_name, now)
                if age is not None:
                    queue_age.add_metric([label], age)

        for queue_name in _UNACKED_QUEUES:
            label = _QUEUE_LABEL_MAP[queue_name]
            task_ids = celery_get_unacked_task_ids(queue_name, redis_client)
            unacked.add_metric([label], len(task_ids))

        return [depth, unacked, queue_age]

    @staticmethod
    def _get_oldest_message_age(
        redis_client: Redis, queue_name: str, now: float
    ) -> float | None:
        """Peek at the oldest (tail) message in a Redis list queue
        and extract its timestamp to compute age.

        Note: If the Celery message contains neither ``properties.timestamp``
        nor ``headers.timestamp``, no age metric is emitted for this queue.
        This can happen with custom task producers or non-standard Celery
        protocol versions. The metric will simply be absent rather than
        inaccurate, which is the safest behavior for alerting.
        """
        try:
            raw: bytes | str | None = redis_client.lindex(queue_name, -1)  # ty: ignore[invalid-assignment]
            if raw is None:
                return None
            msg = json.loads(raw)
            # Check for ETA tasks first — they are intentionally delayed,
            # so reporting their queue age would be misleading.
            headers = msg.get("headers", {})
            if headers.get("eta") is not None:
                return None
            # Celery v2 protocol: timestamp in properties
            props = msg.get("properties", {})
            ts = props.get("timestamp")
            if ts is not None:
                return now - float(ts)
            # Fallback: some Celery configurations place the timestamp in
            # headers instead of properties.
            ts = headers.get("timestamp")
            if ts is not None:
                return now - float(ts)
        except Exception:
            pass
        return None


class RedisHealthCollector(_CachedCollector):
    """Collects Redis server health metrics (memory, clients, etc.)."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._celery_app: Any | None = None

    def set_celery_app(self, app: Any) -> None:
        """Set the Celery app for broker Redis access."""
        self._celery_app = app

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._celery_app is None:
            return []

        redis_client = celery_get_broker_client(self._celery_app)

        memory_used = GaugeMetricFamily(
            "onyx_redis_memory_used_bytes",
            "Redis used memory in bytes",
        )
        memory_peak = GaugeMetricFamily(
            "onyx_redis_memory_peak_bytes",
            "Redis peak used memory in bytes",
        )
        memory_frag = GaugeMetricFamily(
            "onyx_redis_memory_fragmentation_ratio",
            "Redis memory fragmentation ratio (>1.5 indicates fragmentation)",
        )
        connected_clients = GaugeMetricFamily(
            "onyx_redis_connected_clients",
            "Number of connected Redis clients",
        )

        try:
            mem_info: dict = redis_client.info(  # ty: ignore[invalid-assignment]
                "memory"
            )
            memory_used.add_metric([], mem_info.get("used_memory", 0))
            memory_peak.add_metric([], mem_info.get("used_memory_peak", 0))
            frag = mem_info.get("mem_fragmentation_ratio")
            if frag is not None:
                memory_frag.add_metric([], frag)

            client_info: dict = redis_client.info(  # ty: ignore[invalid-assignment]
                "clients"
            )
            connected_clients.add_metric([], client_info.get("connected_clients", 0))
        except Exception:
            logger.debug("Failed to collect Redis health metrics", exc_info=True)

        return [memory_used, memory_peak, memory_frag, connected_clients]


class WorkerHeartbeatMonitor:
    """Monitors Celery worker health via the event stream.

    Subscribes to ``worker-heartbeat``, ``worker-online``, and
    ``worker-offline`` events via a single persistent connection.
    Runs in a daemon thread started once during worker setup.
    """

    # Consider a worker down if no heartbeat received for this long.
    _HEARTBEAT_TIMEOUT_SECONDS = 120.0

    def __init__(self, celery_app: Any) -> None:
        self._app = celery_app
        self._worker_last_seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background event listener thread.

        Safe to call multiple times — only starts one thread.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        logger.info("WorkerHeartbeatMonitor started")

    def stop(self) -> None:
        self._running = False

    def _listen(self) -> None:
        """Background loop: connect to event stream and process heartbeats."""
        while self._running:
            try:
                with self._app.connection() as conn:
                    recv = self._app.events.Receiver(
                        conn,
                        handlers={
                            "worker-heartbeat": self._on_heartbeat,
                            "worker-online": self._on_heartbeat,
                            "worker-offline": self._on_offline,
                        },
                    )
                    recv.capture(
                        limit=None,
                        timeout=self._HEARTBEAT_TIMEOUT_SECONDS,
                        wakeup=True,
                    )
            except Exception:
                if self._running:
                    logger.debug(
                        "Heartbeat listener disconnected, reconnecting in 5s",
                        exc_info=True,
                    )
                    time.sleep(5.0)
            else:
                # capture() returned normally (timeout with no events); reconnect
                if self._running:
                    logger.debug("Heartbeat capture timed out, reconnecting")
                    time.sleep(5.0)

    def _on_heartbeat(self, event: dict[str, Any]) -> None:
        hostname = event.get("hostname")
        if hostname:
            with self._lock:
                self._worker_last_seen[hostname] = time.monotonic()

    def _on_offline(self, event: dict[str, Any]) -> None:
        hostname = event.get("hostname")
        if hostname:
            with self._lock:
                self._worker_last_seen.pop(hostname, None)

    def get_worker_status(self) -> dict[str, bool]:
        """Return {hostname: is_alive} for all known workers.

        Thread-safe. Called by WorkerHealthCollector on each scrape.
        Also prunes workers that have been dead longer than 2x the
        heartbeat timeout to prevent unbounded growth.
        """
        now = time.monotonic()
        prune_threshold = self._HEARTBEAT_TIMEOUT_SECONDS * 2
        with self._lock:
            # Prune workers that have been gone for 2x the timeout
            stale = [
                h
                for h, ts in self._worker_last_seen.items()
                if (now - ts) > prune_threshold
            ]
            for h in stale:
                del self._worker_last_seen[h]

            result: dict[str, bool] = {}
            for hostname, last_seen in self._worker_last_seen.items():
                alive = (now - last_seen) < self._HEARTBEAT_TIMEOUT_SECONDS
                result[hostname] = alive
            return result


class WorkerHealthCollector(_CachedCollector):
    """Collects Celery worker health from the heartbeat monitor.

    Reads worker status from ``WorkerHeartbeatMonitor`` which listens
    to the Celery event stream via a single persistent connection.

    TODO: every monitoring pod subscribes to the cluster-wide Celery event
    stream, so each replica reports health for *all* workers in the cluster,
    not just itself. Prometheus distinguishes the replicas via the ``instance``
    label, so this doesn't break scraping, but it means N monitoring replicas
    do N× the work and may emit slightly inconsistent snapshots of the same
    cluster. The proper fix is to have each worker expose its own health (or
    to elect a single monitoring replica as the reporter) rather than
    broadcasting the full cluster view from every monitoring pod.
    """

    def __init__(self, cache_ttl: float = 30.0) -> None:
        super().__init__(cache_ttl)
        self._monitor: WorkerHeartbeatMonitor | None = None

    def set_monitor(self, monitor: WorkerHeartbeatMonitor) -> None:
        """Set the heartbeat monitor instance."""
        self._monitor = monitor

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._monitor is None:
            return []

        active_workers = GaugeMetricFamily(
            "onyx_celery_active_worker_count",
            "Number of active Celery workers with recent heartbeats",
        )
        # Celery hostnames are ``{worker_type}@{nodename}`` (see supervisord.conf).
        # Emitting only the worker_type as a label causes N replicas of the same
        # type to collapse into identical timeseries within a single scrape,
        # which Prometheus rejects as "duplicate sample for timestamp". Split
        # the pieces into separate labels so each replica is distinct; callers
        # can still ``sum by (worker_type)`` to recover the old aggregated view.
        worker_up = GaugeMetricFamily(
            "onyx_celery_worker_up",
            "Whether a specific Celery worker is alive (1=up, 0=down)",
            labels=["worker_type", "hostname"],
        )

        try:
            status = self._monitor.get_worker_status()
            alive_count = sum(1 for alive in status.values() if alive)
            active_workers.add_metric([], alive_count)

            for full_hostname in sorted(status):
                worker_type, sep, host = full_hostname.partition("@")
                if not sep:
                    # Hostname didn't contain "@" — fall back to using the
                    # whole string as the hostname with an empty type.
                    worker_type, host = "", full_hostname
                worker_up.add_metric(
                    [worker_type, host], 1 if status[full_hostname] else 0
                )
        except Exception:
            logger.debug("Failed to collect worker health metrics", exc_info=True)

        return [active_workers, worker_up]
