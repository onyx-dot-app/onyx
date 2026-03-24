"""Prometheus collectors for Celery queue depths and indexing pipeline state.

These collectors query Redis and Postgres at scrape time (the Collector pattern),
so metrics are always fresh when Prometheus scrapes /metrics. They run inside the
monitoring celery worker which already has Redis and DB access.

To avoid hammering Redis/Postgres on every 15s scrape, results are cached with
a configurable TTL (default 30s). This means metrics may be up to TTL seconds
stale, which is fine for monitoring dashboards.
"""

import time
from collections.abc import Callable
from datetime import datetime
from datetime import timezone

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from redis import Redis
from sqlalchemy import func

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
        self._cached_result: list[GaugeMetricFamily] = []
        self._last_collect_time: float = 0.0

    def collect(self) -> list[GaugeMetricFamily]:
        now = time.monotonic()
        if now - self._last_collect_time < self._cache_ttl and self._cached_result:
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
            return self._cached_result

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

        for queue_name, label in _QUEUE_LABEL_MAP.items():
            length = celery_get_queue_length(queue_name, redis_client)
            depth.add_metric([label], length)

        for queue_name in _UNACKED_QUEUES:
            label = _QUEUE_LABEL_MAP[queue_name]
            task_ids = celery_get_unacked_task_ids(queue_name, redis_client)
            unacked.add_metric([label], len(task_ids))

        return [depth, unacked]


class IndexAttemptCollector(_CachedCollector):
    """Queries Postgres for index attempt state on each scrape."""

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL) -> None:
        super().__init__(cache_ttl)
        self._configured: bool = False

    def configure(self) -> None:
        """Call once DB engine is initialized."""
        self._configured = True

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if not self._configured:
            return []

        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.engine.tenant_utils import get_all_tenant_ids
        from onyx.db.enums import IndexingStatus
        from onyx.db.models import Connector
        from onyx.db.models import ConnectorCredentialPair
        from onyx.db.models import IndexAttempt
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        terminal_statuses = [s for s in IndexingStatus if s.is_terminal()]

        attempts_gauge = GaugeMetricFamily(
            "onyx_index_attempts_active",
            "Number of non-terminal index attempts",
            labels=["status", "source", "tenant_id"],
        )

        tenant_ids = get_all_tenant_ids()

        for tid in tenant_ids:
            if tid is None:
                continue
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tid)
            try:
                with get_session_with_current_tenant() as session:
                    rows = (
                        session.query(
                            IndexAttempt.status,
                            Connector.source,
                            func.count(),
                        )
                        .join(
                            ConnectorCredentialPair,
                            IndexAttempt.connector_credential_pair_id
                            == ConnectorCredentialPair.id,
                        )
                        .join(
                            Connector,
                            ConnectorCredentialPair.connector_id == Connector.id,
                        )
                        .filter(IndexAttempt.status.notin_(terminal_statuses))
                        .group_by(IndexAttempt.status, Connector.source)
                        .all()
                    )

                    for status, source, count in rows:
                        attempts_gauge.add_metric(
                            [status.value, source.value, tid],
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

        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.engine.tenant_utils import get_all_tenant_ids
        from onyx.db.models import Connector
        from onyx.db.models import ConnectorCredentialPair
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        staleness_gauge = GaugeMetricFamily(
            "onyx_connector_last_success_age_seconds",
            "Seconds since last successful index for this connector",
            labels=["tenant_id", "source", "cc_pair_id"],
        )
        error_state_gauge = GaugeMetricFamily(
            "onyx_connector_in_error_state",
            "Whether the connector is in a repeated error state (1=yes, 0=no)",
            labels=["tenant_id", "source", "cc_pair_id"],
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
            labels=["tenant_id", "source", "cc_pair_id"],
        )

        now = datetime.now(tz=timezone.utc)
        tenant_ids = get_all_tenant_ids()

        for tid in tenant_ids:
            if tid is None:
                continue
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tid)
            try:
                with get_session_with_current_tenant() as session:
                    pairs = (
                        session.query(
                            ConnectorCredentialPair.id,
                            ConnectorCredentialPair.status,
                            ConnectorCredentialPair.in_repeated_error_state,
                            ConnectorCredentialPair.last_successful_index_time,
                            ConnectorCredentialPair.total_docs_indexed,
                            Connector.source,
                        )
                        .join(
                            Connector,
                            ConnectorCredentialPair.connector_id == Connector.id,
                        )
                        .all()
                    )

                    status_counts: dict[str, int] = {}
                    error_count = 0

                    for (
                        cc_id,
                        status,
                        in_error,
                        last_success,
                        total_docs,
                        source,
                    ) in pairs:
                        cc_id_str = str(cc_id)
                        source_val = source.value

                        if last_success is not None:
                            age = (now - last_success).total_seconds()
                            staleness_gauge.add_metric(
                                [tid, source_val, cc_id_str], age
                            )

                        error_state_gauge.add_metric(
                            [tid, source_val, cc_id_str],
                            1.0 if in_error else 0.0,
                        )
                        if in_error:
                            error_count += 1

                        docs_gauge.add_metric(
                            [tid, source_val, cc_id_str],
                            total_docs or 0,
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
        ]
