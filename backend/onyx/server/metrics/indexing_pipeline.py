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
        and extract its timestamp to compute age."""
        try:
            raw = redis_client.lindex(queue_name, -1)
            if raw is None:
                return None
            msg = json.loads(raw)
            # Celery v2 protocol: timestamp in properties
            props = msg.get("properties", {})
            ts = props.get("timestamp")
            if ts is not None:
                return now - float(ts)
            # Fallback: check headers for eta or expires
            headers = msg.get("headers", {})
            if "eta" in headers and headers["eta"] is not None:
                return None  # ETA tasks are intentionally delayed
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
        docs_gauge = GaugeMetricFamily(
            "onyx_connector_total_docs_indexed",
            "Total documents indexed by this connector",
            labels=["tenant_id", "source", "cc_pair_id", "connector_name"],
        )

        per_connector_labels = [
            "tenant_id",
            "source",
            "cc_pair_id",
            "connector_name",
        ]
        docs_success_gauge = GaugeMetricFamily(
            "onyx_connector_docs_indexed_total",
            "Total documents successfully indexed (from latest attempt) per connector",
            labels=per_connector_labels,
        )
        docs_error_gauge = GaugeMetricFamily(
            "onyx_connector_error_count_total",
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
                            age = (now - last_success).total_seconds()
                            staleness_gauge.add_metric(label_vals, age)

                        error_state_gauge.add_metric(
                            label_vals,
                            1.0 if in_error else 0.0,
                        )
                        if in_error:
                            error_count += 1

                        docs_gauge.add_metric(
                            label_vals,
                            docs_by_cc.get(cc_id, 0),
                        )

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
            docs_gauge,
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
            mem_info = redis_client.info("memory")
            memory_used.add_metric([], mem_info.get("used_memory", 0))
            memory_peak.add_metric([], mem_info.get("used_memory_peak", 0))
            memory_frag.add_metric([], mem_info.get("mem_fragmentation_ratio", 0))

            client_info = redis_client.info("clients")
            connected_clients.add_metric([], client_info.get("connected_clients", 0))
        except Exception:
            logger.debug("Failed to collect Redis health metrics", exc_info=True)

        return [memory_used, memory_peak, memory_frag, connected_clients]


class WorkerHealthCollector(_CachedCollector):
    """Collects Celery worker count and process count via inspect ping.

    Uses a longer cache TTL (60s) since inspect.ping() is a broadcast
    command that takes a couple seconds to complete.
    """

    def __init__(self, cache_ttl: float = 60.0) -> None:
        super().__init__(cache_ttl)
        self._celery_app: Any | None = None

    def set_celery_app(self, app: Any) -> None:
        """Set the Celery app instance for inspect commands."""
        self._celery_app = app

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if self._celery_app is None:
            return []

        active_workers = GaugeMetricFamily(
            "onyx_celery_active_worker_count",
            "Number of active Celery workers responding to ping",
        )
        worker_up = GaugeMetricFamily(
            "onyx_celery_worker_up",
            "Whether a specific Celery worker is alive (1=up, 0=down)",
            labels=["worker"],
        )

        try:
            inspector = self._celery_app.control.inspect(timeout=3.0)
            ping_result = inspector.ping()
            if ping_result:
                active_workers.add_metric([], len(ping_result))
                for worker_name in ping_result:
                    # Strip hostname suffix for cleaner labels
                    short_name = worker_name.split("@")[0]
                    worker_up.add_metric([short_name], 1)
            else:
                active_workers.add_metric([], 0)
        except Exception:
            logger.debug("Failed to collect worker health metrics", exc_info=True)

        return [active_workers, worker_up]
