"""DB-snapshot connector state metrics.

Complements connector_health_metrics.py: those are event-driven counters
emitted from the celery workers, so they reset on worker restart and say
nothing about connectors that haven't run since. This collector reads the
current state straight from Postgres on each scrape, giving absolute truth
for staleness alerting (e.g. "connector hasn't indexed successfully in N
hours") regardless of process restarts.

Registered on the API server (see main.py); one cheap query per scrape.
Skipped in multi-tenant deployments — a scrape-time collector has no tenant
context to enumerate.
"""

import logging
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.core import InfoMetricFamily
from prometheus_client.core import Metric
from prometheus_client.core import REGISTRY
from prometheus_client.registry import Collector

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import User
from shared_configs.configs import MULTI_TENANT

logger = logging.getLogger(__name__)

# One-hot label values; anything else is reported as UNKNOWN so a new enum
# value can't silently create an unbounded label set.
_VALID_CC_PAIR_STATUSES = ("ACTIVE", "PAUSED", "DELETING")
_VALID_ACCESS_TYPES = ("PUBLIC", "PRIVATE", "SYNC")
_VALID_INDEXING_MODES = ("SCHEDULED", "ON_DEMAND")


def _to_unix_ts(dt: datetime | None) -> int:
    """Convert datetime to Unix timestamp, return 0 if None."""
    if not dt:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _enum_str(value: object, valid: tuple[str, ...]) -> str:
    raw = getattr(value, "value", None) or getattr(value, "name", None) or str(value)
    return raw if raw in valid else "UNKNOWN"


class ConnectorStateMetricsCollector(Collector):
    """Prometheus collector exposing per-cc-pair state gauges from the DB."""

    def collect(self) -> Iterator[Metric]:
        g_last_pruned = GaugeMetricFamily(
            "onyx_connector_last_pruned_timestamp_seconds",
            "Unix timestamp of the last successful prune operation (0 if never).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_last_perm_sync = GaugeMetricFamily(
            "onyx_connector_last_perm_sync_timestamp_seconds",
            "Unix timestamp of the last permission sync (0 if never).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_last_external_group_sync = GaugeMetricFamily(
            "onyx_connector_last_external_group_sync_timestamp_seconds",
            "Unix timestamp of the last external group sync (0 if never).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_cc_pair_status = GaugeMetricFamily(
            "onyx_connector_status",
            "Current connector credential pair status as one-hot encoding.",
            labels=["cc_pair_id", "cc_pair_name", "source_type", "status"],
        )
        g_access_type = GaugeMetricFamily(
            "onyx_connector_access_type",
            "Access type of the connector as one-hot encoding.",
            labels=["cc_pair_id", "cc_pair_name", "source_type", "access_type"],
        )
        g_indexing_trigger = GaugeMetricFamily(
            "onyx_connector_indexing_trigger",
            "Indexing trigger mode as one-hot encoding.",
            labels=["cc_pair_id", "cc_pair_name", "source_type", "trigger_mode"],
        )
        g_auto_sync_enabled = GaugeMetricFamily(
            "onyx_connector_auto_sync_enabled",
            "Whether auto-sync is configured (1 = enabled, 0 = disabled).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_time_since_last_success = GaugeMetricFamily(
            "onyx_connector_seconds_since_last_success",
            "Seconds since the last successful indexing (0 if never indexed).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_time_since_last_prune = GaugeMetricFamily(
            "onyx_connector_seconds_since_last_prune",
            "Seconds since the last prune operation (0 if never pruned).",
            labels=["cc_pair_id", "cc_pair_name", "source_type"],
        )
        g_total_connectors = GaugeMetricFamily(
            "onyx_connectors_total",
            "Total number of connector credential pairs by source type and status.",
            labels=["source_type", "status"],
        )
        g_total_docs_by_source = GaugeMetricFamily(
            "onyx_connector_docs_by_source_total",
            "Total documents currently indexed across all connectors by source type.",
            labels=["source_type"],
        )
        g_connector_info = InfoMetricFamily(
            "onyx_connector",
            "Metadata information about connector credential pairs.",
            labels=["cc_pair_id"],
        )

        try:
            with get_session_with_current_tenant() as db:
                rows = (
                    db.query(
                        ConnectorCredentialPair.id,
                        ConnectorCredentialPair.name,
                        ConnectorCredentialPair.status,
                        ConnectorCredentialPair.last_successful_index_time,
                        ConnectorCredentialPair.last_pruned,
                        ConnectorCredentialPair.last_time_perm_sync,
                        ConnectorCredentialPair.last_time_external_group_sync,
                        ConnectorCredentialPair.total_docs_indexed,
                        ConnectorCredentialPair.access_type,
                        ConnectorCredentialPair.indexing_trigger,
                        ConnectorCredentialPair.auto_sync_options,
                        Connector.source,
                        Credential.id,
                        Credential.name,
                        User.email,  # ty: ignore[invalid-argument-type]
                    )
                    .join(ConnectorCredentialPair.connector)
                    .join(ConnectorCredentialPair.credential)
                    .outerjoin(ConnectorCredentialPair.creator)
                    .filter(ConnectorCredentialPair.name != "DefaultCCPair")
                    .all()
                )

            connector_counts: dict[tuple[str, str], int] = {}
            docs_by_source: dict[str, int] = {}
            current_time = datetime.now(timezone.utc)

            for (
                cc_pair_id,
                cc_pair_name,
                status,
                last_successful_index_time,
                last_pruned,
                last_time_perm_sync,
                last_time_external_group_sync,
                total_docs_indexed,
                access_type,
                indexing_trigger,
                auto_sync_options,
                source,
                credential_id,
                credential_name,
                creator_email,
            ) in rows:
                cc_pair_id_str = str(cc_pair_id)
                cc_pair_name_str = cc_pair_name or ""
                source_str = (
                    getattr(source, "value", None)
                    or getattr(source, "name", None)
                    or str(source)
                )
                status_str = _enum_str(status, _VALID_CC_PAIR_STATUSES)
                access_type_str = _enum_str(access_type, _VALID_ACCESS_TYPES)
                indexing_trigger_str = (
                    _enum_str(indexing_trigger, _VALID_INDEXING_MODES)
                    if indexing_trigger
                    else "NONE"
                )

                common_labels = [cc_pair_id_str, cc_pair_name_str, source_str]

                g_last_pruned.add_metric(common_labels, float(_to_unix_ts(last_pruned)))
                g_last_perm_sync.add_metric(
                    common_labels, float(_to_unix_ts(last_time_perm_sync))
                )
                g_last_external_group_sync.add_metric(
                    common_labels,
                    float(_to_unix_ts(last_time_external_group_sync)),
                )

                for st in _VALID_CC_PAIR_STATUSES:
                    g_cc_pair_status.add_metric(
                        [*common_labels, st], 1.0 if st == status_str else 0.0
                    )
                for at in _VALID_ACCESS_TYPES:
                    g_access_type.add_metric(
                        [*common_labels, at], 1.0 if at == access_type_str else 0.0
                    )
                for mode in [*_VALID_INDEXING_MODES, "NONE"]:
                    g_indexing_trigger.add_metric(
                        [*common_labels, mode],
                        1.0 if mode == indexing_trigger_str else 0.0,
                    )

                g_auto_sync_enabled.add_metric(
                    common_labels, 1.0 if auto_sync_options else 0.0
                )

                if last_successful_index_time:
                    seconds_since_success = (
                        current_time
                        - last_successful_index_time.replace(tzinfo=timezone.utc)
                    ).total_seconds()
                    g_time_since_last_success.add_metric(
                        common_labels, max(0.0, seconds_since_success)
                    )
                else:
                    g_time_since_last_success.add_metric(common_labels, 0.0)

                if last_pruned:
                    seconds_since_prune = (
                        current_time - last_pruned.replace(tzinfo=timezone.utc)
                    ).total_seconds()
                    g_time_since_last_prune.add_metric(
                        common_labels, max(0.0, seconds_since_prune)
                    )
                else:
                    g_time_since_last_prune.add_metric(common_labels, 0.0)

                g_connector_info.add_metric(
                    [cc_pair_id_str],
                    {
                        "cc_pair_name": cc_pair_name_str,
                        "source_type": source_str,
                        "credential_id": str(credential_id),
                        "credential_name": credential_name or "",
                        "creator_email": creator_email or "unknown",
                        "status": status_str,
                        "access_type": access_type_str,
                    },
                )

                connector_counts[(source_str, status_str)] = (
                    connector_counts.get((source_str, status_str), 0) + 1
                )
                docs_by_source[source_str] = docs_by_source.get(source_str, 0) + (
                    total_docs_indexed or 0
                )

            for (source_type, status_val), count in connector_counts.items():
                g_total_connectors.add_metric([source_type, status_val], float(count))
            for source_type, total_docs in docs_by_source.items():
                g_total_docs_by_source.add_metric([source_type], float(total_docs))

        except RuntimeError as e:
            if "Engine not initialized" in str(e):
                logger.warning(
                    "Database engine not initialized yet, "
                    "skipping connector state metrics collection"
                )
            else:
                logger.error(
                    "Error collecting connector state metrics: %s", e, exc_info=True
                )
        except Exception as e:
            logger.error(
                "Unexpected error collecting connector state metrics: %s",
                e,
                exc_info=True,
            )

        # Always yield metric families, even if empty.
        yield g_last_pruned
        yield g_last_perm_sync
        yield g_last_external_group_sync
        yield g_cc_pair_status
        yield g_access_type
        yield g_indexing_trigger
        yield g_auto_sync_enabled
        yield g_time_since_last_success
        yield g_time_since_last_prune
        yield g_total_connectors
        yield g_total_docs_by_source
        yield g_connector_info


def register_connector_state_metrics() -> None:
    """Register the connector state collector with the default registry."""
    if MULTI_TENANT:
        # A scrape-time collector has no tenant context; per-tenant state
        # metrics need a different mechanism in cloud deployments.
        logger.info(
            "Multi-tenant deployment — skipping connector state metrics collector"
        )
        return
    try:
        REGISTRY.register(ConnectorStateMetricsCollector())
        logger.info("Connector state metrics collector registered")
    except ValueError:
        logger.debug("Connector state metrics collector already registered")
