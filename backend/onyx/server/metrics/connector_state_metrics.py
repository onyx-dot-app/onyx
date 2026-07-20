"""Restart-proof connector state metrics for single-tenant deployments."""

import concurrent.futures
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import NamedTuple

from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily, Metric, REGISTRY
from prometheus_client.registry import Collector

from onyx.db.connector_credential_pair import get_connector_state_snapshots
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, IndexingMode
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

_UNKNOWN_LABEL = "UNKNOWN"
_NO_TRIGGER_LABEL = "NONE"
_CC_PAIR_STATUS_LABELS = tuple(
    status.value for status in ConnectorCredentialPairStatus
) + (_UNKNOWN_LABEL,)
_ACCESS_TYPE_LABELS = tuple(access_type.value for access_type in AccessType) + (
    _UNKNOWN_LABEL,
)
_INDEXING_MODE_LABELS = tuple(mode.value for mode in IndexingMode) + (
    _NO_TRIGGER_LABEL,
    _UNKNOWN_LABEL,
)
_CONNECTOR_LABELS = ["source", "cc_pair_id"]
_COLLECTION_TIMEOUT_SECONDS = 8.0


def _to_unix_ts(dt: datetime | None) -> int:
    if not dt:
        return 0
    return int(datetime_to_utc(dt).timestamp())


def _enum_label(value: object, valid: tuple[str, ...]) -> str:
    raw = getattr(value, "value", None) or getattr(value, "name", None) or str(value)
    return raw if raw in valid else _UNKNOWN_LABEL


class _ConnectorMetricFamilies(NamedTuple):
    last_success: GaugeMetricFamily
    last_pruned: GaugeMetricFamily
    last_perm_sync: GaugeMetricFamily
    last_external_group_sync: GaugeMetricFamily
    repeated_error: GaugeMetricFamily
    cc_pair_status: GaugeMetricFamily
    access_type: GaugeMetricFamily
    indexing_trigger: GaugeMetricFamily
    auto_sync_enabled: GaugeMetricFamily
    connector_count: GaugeMetricFamily
    document_count: GaugeMetricFamily
    connector_info: InfoMetricFamily


def _create_metric_families() -> _ConnectorMetricFamilies:
    return _ConnectorMetricFamilies(
        last_success=GaugeMetricFamily(
            "onyx_connector_last_successful_index_timestamp_seconds",
            "Unix timestamp of the last successful indexing (0 if never).",
            labels=_CONNECTOR_LABELS,
        ),
        last_pruned=GaugeMetricFamily(
            "onyx_connector_last_pruned_timestamp_seconds",
            "Unix timestamp of the last successful prune operation (0 if never).",
            labels=_CONNECTOR_LABELS,
        ),
        last_perm_sync=GaugeMetricFamily(
            "onyx_connector_last_perm_sync_timestamp_seconds",
            "Unix timestamp of the last permission sync (0 if never).",
            labels=_CONNECTOR_LABELS,
        ),
        last_external_group_sync=GaugeMetricFamily(
            "onyx_connector_last_external_group_sync_timestamp_seconds",
            "Unix timestamp of the last external group sync (0 if never).",
            labels=_CONNECTOR_LABELS,
        ),
        repeated_error=GaugeMetricFamily(
            "onyx_connector_repeated_error_state",
            "Whether the connector is in a repeated error state.",
            labels=_CONNECTOR_LABELS,
        ),
        cc_pair_status=GaugeMetricFamily(
            "onyx_connector_status",
            "Current connector credential pair status as one-hot encoding.",
            labels=[*_CONNECTOR_LABELS, "status"],
        ),
        access_type=GaugeMetricFamily(
            "onyx_connector_access_type",
            "Access type of the connector as one-hot encoding.",
            labels=[*_CONNECTOR_LABELS, "access_type"],
        ),
        indexing_trigger=GaugeMetricFamily(
            "onyx_connector_indexing_trigger",
            "Indexing trigger mode as one-hot encoding.",
            labels=[*_CONNECTOR_LABELS, "trigger_mode"],
        ),
        auto_sync_enabled=GaugeMetricFamily(
            "onyx_connector_auto_sync_enabled",
            "Whether auto-sync is configured (1 = enabled, 0 = disabled).",
            labels=_CONNECTOR_LABELS,
        ),
        connector_count=GaugeMetricFamily(
            "onyx_connector_count",
            "Current connector credential pair count by source and status.",
            labels=["source", "status"],
        ),
        document_count=GaugeMetricFamily(
            "onyx_connector_document_count",
            "Current indexed document count across connectors by source.",
            labels=["source"],
        ),
        connector_info=InfoMetricFamily(
            "onyx_connector",
            "Connector credential pair metadata.",
            labels=["cc_pair_id"],
        ),
    )


def _collection_success_metric() -> GaugeMetricFamily:
    return GaugeMetricFamily(
        "onyx_connector_state_collection_success",
        "Whether the latest connector state collection succeeded.",
    )


class ConnectorStateMetricsCollector(Collector):
    """Build connector state gauges from the current Postgres snapshot."""

    def __init__(self, timeout: float = _COLLECTION_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=type(self).__name__,
        )
        self._inflight: concurrent.futures.Future[list[Metric]] | None = None
        self._lock = threading.Lock()

    def collect(self) -> Iterator[Metric]:
        collection_success = _collection_success_metric()
        with self._lock:
            if self._inflight is not None and self._inflight.done():
                self._inflight = None
            if self._inflight is None:
                self._inflight = self._executor.submit(self._collect_fresh)
                future: concurrent.futures.Future[list[Metric]] | None = self._inflight
            else:
                future = None

        if future is None:
            metrics: list[Metric] = []
            collection_success.add_metric([], 0.0)
        else:
            try:
                metrics = future.result(timeout=self._timeout)
                collection_success.add_metric([], 1.0)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "Connector state collection timed out after %ss",
                    self._timeout,
                )
                metrics = []
                collection_success.add_metric([], 0.0)
            except Exception:
                logger.exception("Connector state collection failed")
                metrics = []
                collection_success.add_metric([], 0.0)
            finally:
                if future.done():
                    with self._lock:
                        if self._inflight is future:
                            self._inflight = None

        yield collection_success
        yield from metrics

    def describe(self) -> Iterator[Metric]:
        yield _collection_success_metric()
        yield from _create_metric_families()

    def _collect_fresh(self) -> list[Metric]:
        families = _create_metric_families()
        g_last_success = families.last_success
        g_last_pruned = families.last_pruned
        g_last_perm_sync = families.last_perm_sync
        g_last_external_group_sync = families.last_external_group_sync
        g_repeated_error = families.repeated_error
        g_cc_pair_status = families.cc_pair_status
        g_access_type = families.access_type
        g_indexing_trigger = families.indexing_trigger
        g_auto_sync_enabled = families.auto_sync_enabled
        g_connector_count = families.connector_count
        g_document_count = families.document_count
        g_connector_info = families.connector_info
        with get_session_with_current_tenant() as db:
            snapshots = get_connector_state_snapshots(db)

        connector_counts: dict[tuple[str, str], int] = {}
        docs_by_source: dict[str, int] = {}

        for snapshot in snapshots:
            cc_pair_id_str = str(snapshot.cc_pair_id)
            source_str = snapshot.source.value
            status_str = _enum_label(snapshot.status, _CC_PAIR_STATUS_LABELS)
            access_type_str = _enum_label(snapshot.access_type, _ACCESS_TYPE_LABELS)
            indexing_trigger_str = (
                _enum_label(snapshot.indexing_trigger, _INDEXING_MODE_LABELS)
                if snapshot.indexing_trigger
                else _NO_TRIGGER_LABEL
            )

            common_labels = [source_str, cc_pair_id_str]

            g_last_success.add_metric(
                common_labels,
                float(_to_unix_ts(snapshot.last_successful_index_time)),
            )
            g_last_pruned.add_metric(
                common_labels, float(_to_unix_ts(snapshot.last_pruned))
            )
            g_last_perm_sync.add_metric(
                common_labels,
                float(_to_unix_ts(snapshot.last_time_perm_sync)),
            )
            g_last_external_group_sync.add_metric(
                common_labels,
                float(_to_unix_ts(snapshot.last_time_external_group_sync)),
            )
            g_repeated_error.add_metric(
                common_labels,
                1.0 if snapshot.in_repeated_error_state else 0.0,
            )

            for status_label in _CC_PAIR_STATUS_LABELS:
                g_cc_pair_status.add_metric(
                    [*common_labels, status_label],
                    1.0 if status_label == status_str else 0.0,
                )
            for access_type_label in _ACCESS_TYPE_LABELS:
                g_access_type.add_metric(
                    [*common_labels, access_type_label],
                    1.0 if access_type_label == access_type_str else 0.0,
                )
            for mode_label in _INDEXING_MODE_LABELS:
                g_indexing_trigger.add_metric(
                    [*common_labels, mode_label],
                    1.0 if mode_label == indexing_trigger_str else 0.0,
                )

            g_auto_sync_enabled.add_metric(
                common_labels, 1.0 if snapshot.auto_sync_enabled else 0.0
            )

            g_connector_info.add_metric(
                [cc_pair_id_str],
                {
                    "connector_name": snapshot.cc_pair_name,
                    "source": source_str,
                    "credential_id": str(snapshot.credential_id),
                    "status": status_str,
                    "access_type": access_type_str,
                },
            )

            connector_counts[(source_str, status_str)] = (
                connector_counts.get((source_str, status_str), 0) + 1
            )
            docs_by_source[source_str] = (
                docs_by_source.get(source_str, 0) + snapshot.total_docs_indexed
            )

        for (source, status), count in connector_counts.items():
            g_connector_count.add_metric([source, status], float(count))
        for source, total_docs in docs_by_source.items():
            g_document_count.add_metric([source], float(total_docs))

        return list(families)


_CONNECTOR_STATE_COLLECTOR = ConnectorStateMetricsCollector()
_CONNECTOR_STATE_COLLECTOR_REGISTERED = False


def register_connector_state_metrics() -> None:
    global _CONNECTOR_STATE_COLLECTOR_REGISTERED
    if MULTI_TENANT:
        logger.info(
            "Multi-tenant deployment — skipping connector state metrics collector"
        )
        return
    if _CONNECTOR_STATE_COLLECTOR_REGISTERED:
        logger.debug("Connector state metrics collector already registered")
        return
    REGISTRY.register(_CONNECTOR_STATE_COLLECTOR)
    _CONNECTOR_STATE_COLLECTOR_REGISTERED = True
    logger.info("Connector state metrics collector registered")
