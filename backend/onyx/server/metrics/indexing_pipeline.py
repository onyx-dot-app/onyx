"""Prometheus collectors for Celery queue depths and indexing pipeline state.

These collectors query Redis and Postgres at scrape time (the Collector pattern),
so metrics are always fresh when Prometheus scrapes /metrics. They run inside the
monitoring celery worker which already has Redis and DB access.

To avoid hammering Redis/Postgres on every 15s scrape, results are cached with
a configurable TTL (default 30s). This means metrics may be up to TTL seconds
stale, which is fine for monitoring dashboards.
"""

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from redis import Redis

from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.configs.constants import OnyxCeleryQueues
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Default cache TTL in seconds. Scrapes hitting within this window return
# the previous result without re-querying Redis/Postgres.
_DEFAULT_CACHE_TTL = 30.0

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
    """Base collector with TTL-based caching.

    Subclasses implement ``_collect_fresh()`` to query the actual data source.
    The base ``collect()`` returns cached results if the TTL hasn't expired,
    avoiding repeated queries when Prometheus scrapes frequently.
    """

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        self._cache_ttl = cache_ttl
        self._cached_result: list[GaugeMetricFamily] | None = None
        self._last_collect_time: float = 0.0
        self._lock = threading.Lock()

    def collect(self) -> list[GaugeMetricFamily]:
        with self._lock:
            now = time.monotonic()
            if (
                now - self._last_collect_time < self._cache_ttl
                and self._cached_result is not None
            ):
                return self._cached_result

            try:
                result = self._collect_fresh()
                self._cached_result = result
                self._last_collect_time = now
                return result
            except Exception:
                logger.exception(f"Error in {type(self).__name__}.collect()")
                # Return stale cache on error rather than nothing — avoids
                # metrics disappearing during transient failures.
                return self._cached_result if self._cached_result is not None else []

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        raise NotImplementedError

    def describe(self) -> list[GaugeMetricFamily]:
        return []


class QueueDepthCollector(_CachedCollector):
    """Reads Celery queue lengths from the broker Redis on each scrape.

    Uses a Redis client factory (callable) rather than a stored client
    reference so the connection is always fresh from Celery's pool.
    """

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._get_redis: Callable[[], Redis] | None = None

    def set_redis_factory(self, factory: Callable[[], Redis]) -> None:
        """Set a callable that returns a broker Redis client on demand."""
        self._get_redis = factory

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._get_redis is None:
            return []

        redis_client = self._get_redis()

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
            raw: bytes | str | None = redis_client.lindex(queue_name, -1)  # type: ignore[assignment]
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


class IndexAttemptCollector(_CachedCollector):
    """Queries Postgres for index attempt state on each scrape."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._configured: bool = False
        self._terminal_statuses: list = []

    def configure(self) -> None:
        """Call once DB engine is initialized."""
        from onyx.db.enums import IndexingStatus

        self._terminal_statuses = [s for s in IndexingStatus if s.is_terminal()]
        self._configured = True

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if not self._configured:
            return []

        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.engine.tenant_utils import get_all_tenant_ids
        from onyx.db.index_attempt import get_active_index_attempts_for_metrics
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        attempts_gauge = GaugeMetricFamily(
            "onyx_index_attempts_active",
            "Number of non-terminal index attempts",
            labels=[
                "status",
                "source",
                "tenant_id",
                "connector_name",
                "cc_pair_id",
            ],
        )

        tenant_ids = get_all_tenant_ids()

        for tid in tenant_ids:
            # Defensive guard — get_all_tenant_ids() should never yield None,
            # but we guard here for API stability in case the contract changes.
            if tid is None:
                continue
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tid)
            try:
                with get_session_with_current_tenant() as session:
                    rows = get_active_index_attempts_for_metrics(session)

                    for status, source, cc_id, cc_name, count in rows:
                        name_val = cc_name or f"cc_pair_{cc_id}"
                        attempts_gauge.add_metric(
                            [
                                status.value,
                                source.value,
                                tid,
                                name_val,
                                str(cc_id),
                            ],
                            count,
                        )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        return [attempts_gauge]


class ConnectorHealthCollector(_CachedCollector):
    """Queries Postgres for connector health state on each scrape."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._configured: bool = False

    def configure(self) -> None:
        """Call once DB engine is initialized."""
        self._configured = True

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if not self._configured:
            return []

        from onyx.db.connector_credential_pair import (
            get_connector_health_for_metrics,
        )
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.engine.tenant_utils import get_all_tenant_ids
        from onyx.db.index_attempt import get_docs_indexed_by_cc_pair
        from onyx.db.index_attempt import get_failed_attempt_counts_by_cc_pair
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        staleness_gauge = GaugeMetricFamily(
            "onyx_connector_last_success_age_seconds",
            "Seconds since last successful index for this connector",
            labels=["tenant_id", "source", "cc_pair_id", "connector_name"],
        )
        error_state_gauge = GaugeMetricFamily(
            "onyx_connector_in_error_state",
            "Whether the connector is in a repeated error state (1=yes, 0=no)",
            labels=["tenant_id", "source", "cc_pair_id", "connector_name"],
        )
        by_status_gauge = GaugeMetricFamily(
            "onyx_connectors_by_status",
            "Number of connectors grouped by status",
            labels=["tenant_id", "status"],
        )
        error_total_gauge = GaugeMetricFamily(
            "onyx_connectors_in_error_total",
            "Total number of connectors in repeated error state",
            labels=["tenant_id"],
        )
        per_connector_labels = [
            "tenant_id",
            "source",
            "cc_pair_id",
            "connector_name",
        ]
        docs_success_gauge = GaugeMetricFamily(
            "onyx_connector_docs_indexed",
            "Total new documents indexed (90-day rolling sum) per connector",
            labels=per_connector_labels,
        )
        docs_error_gauge = GaugeMetricFamily(
            "onyx_connector_error_count",
            "Total number of failed index attempts per connector",
            labels=per_connector_labels,
        )

        now = datetime.now(tz=timezone.utc)
        tenant_ids = get_all_tenant_ids()

        for tid in tenant_ids:
            # Defensive guard — get_all_tenant_ids() should never yield None,
            # but we guard here for API stability in case the contract changes.
            if tid is None:
                continue
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tid)
            try:
                with get_session_with_current_tenant() as session:
                    pairs = get_connector_health_for_metrics(session)
                    error_counts_by_cc = get_failed_attempt_counts_by_cc_pair(session)
                    docs_by_cc = get_docs_indexed_by_cc_pair(session)

                    status_counts: dict[str, int] = {}
                    error_count = 0

                    for (
                        cc_id,
                        status,
                        in_error,
                        last_success,
                        cc_name,
                        source,
                    ) in pairs:
                        cc_id_str = str(cc_id)
                        source_val = source.value
                        name_val = cc_name or f"cc_pair_{cc_id}"
                        label_vals = [tid, source_val, cc_id_str, name_val]

                        if last_success is not None:
                            # Both `now` and `last_success` are timezone-aware
                            # (the DB column uses DateTime(timezone=True)),
                            # so subtraction is safe.
                            age = (now - last_success).total_seconds()
                            staleness_gauge.add_metric(label_vals, age)

                        error_state_gauge.add_metric(
                            label_vals,
                            1.0 if in_error else 0.0,
                        )
                        if in_error:
                            error_count += 1

                        docs_success_gauge.add_metric(
                            label_vals,
                            docs_by_cc.get(cc_id, 0),
                        )

                        docs_error_gauge.add_metric(
                            label_vals,
                            error_counts_by_cc.get(cc_id, 0),
                        )

                        status_val = status.value
                        status_counts[status_val] = status_counts.get(status_val, 0) + 1

                    for status_val, count in status_counts.items():
                        by_status_gauge.add_metric([tid, status_val], count)

                    error_total_gauge.add_metric([tid], error_count)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        return [
            staleness_gauge,
            error_state_gauge,
            by_status_gauge,
            error_total_gauge,
            docs_success_gauge,
            docs_error_gauge,
        ]


class RedisHealthCollector(_CachedCollector):
    """Collects Redis server health metrics (memory, clients, etc.)."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._get_redis: Callable[[], Redis] | None = None

    def set_redis_factory(self, factory: Callable[[], Redis]) -> None:
        """Set a callable that returns a broker Redis client on demand."""
        self._get_redis = factory

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._get_redis is None:
            return []

        redis_client = self._get_redis()

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
            mem_info: dict = redis_client.info("memory")  # type: ignore[assignment]
            memory_used.add_metric([], mem_info.get("used_memory", 0))
            memory_peak.add_metric([], mem_info.get("used_memory_peak", 0))
            frag = mem_info.get("mem_fragmentation_ratio")
            if frag is not None:
                memory_frag.add_metric([], frag)

            client_info: dict = redis_client.info("clients")  # type: ignore[assignment]
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
                        limit=None, timeout=self._HEARTBEAT_TIMEOUT_SECONDS, wakeup=True
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
        worker_up = GaugeMetricFamily(
            "onyx_celery_worker_up",
            "Whether a specific Celery worker is alive (1=up, 0=down)",
            labels=["worker"],
        )

        try:
            status = self._monitor.get_worker_status()
            alive_count = sum(1 for alive in status.values() if alive)
            active_workers.add_metric([], alive_count)

            for hostname in sorted(status):
                # Use short name (before @) for single-host deployments,
                # full hostname when multiple hosts share a worker type.
                label = hostname.split("@")[0]
                worker_up.add_metric([label], 1 if status[hostname] else 0)
        except Exception:
            logger.debug("Failed to collect worker health metrics", exc_info=True)

        return [active_workers, worker_up]
