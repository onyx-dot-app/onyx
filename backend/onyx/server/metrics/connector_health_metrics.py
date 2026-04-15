"""Prometheus metrics for connector health and index attempts.

Emitted by docfetching and docprocessing workers when connector or
index attempt state changes. All functions silently catch exceptions
to avoid disrupting the caller's business logic.

Gauge metrics (error state, last success timestamp) are per-process.
With multiple worker pods, use max() aggregation in PromQL to get the
correct value across instances, e.g.:
    max by (cc_pair_id, connector_name) (onyx_connector_in_error_state)

Unlike the per-task counters in indexing_task_metrics.py, these metrics
include connector_name because their cardinality is bounded by the number
of connectors (one series per connector), not by the number of task
executions.
"""

from prometheus_client import Counter
from prometheus_client import Gauge

from onyx.utils.logger import setup_logger

logger = setup_logger()

_CONNECTOR_LABELS = ["tenant_id", "source", "cc_pair_id", "connector_name"]

# --- Index attempt lifecycle ---

INDEX_ATTEMPT_STATUS = Counter(
    "onyx_index_attempt_transitions_total",
    "Index attempt status transitions",
    [*_CONNECTOR_LABELS, "status"],
)

# --- Connector health ---

CONNECTOR_IN_ERROR_STATE = Gauge(
    "onyx_connector_in_error_state",
    "Whether the connector is in a repeated error state (1=yes, 0=no)",
    _CONNECTOR_LABELS,
)

CONNECTOR_LAST_SUCCESS_TIMESTAMP = Gauge(
    "onyx_connector_last_success_timestamp_seconds",
    "Unix timestamp of last successful indexing for this connector",
    _CONNECTOR_LABELS,
)

CONNECTOR_DOCS_INDEXED = Counter(
    "onyx_connector_docs_indexed_total",
    "Total documents indexed per connector (monotonic)",
    _CONNECTOR_LABELS,
)

CONNECTOR_INDEXING_ERRORS = Counter(
    "onyx_connector_indexing_errors_total",
    "Total failed index attempts per connector (monotonic)",
    _CONNECTOR_LABELS,
)


def on_index_attempt_status_change(
    tenant_id: str,
    source: str,
    cc_pair_id: int,
    connector_name: str,
    status: str,
) -> None:
    """Called on any index attempt status transition."""
    try:
        labels = {
            "tenant_id": tenant_id,
            "source": source,
            "cc_pair_id": str(cc_pair_id),
            "connector_name": connector_name,
        }
        INDEX_ATTEMPT_STATUS.labels(**labels, status=status).inc()
        if status == "failed":
            CONNECTOR_INDEXING_ERRORS.labels(**labels).inc()
    except Exception:
        logger.debug("Failed to record index attempt status metric", exc_info=True)


def on_connector_error_state_change(
    tenant_id: str,
    source: str,
    cc_pair_id: int,
    connector_name: str,
    in_error: bool,
) -> None:
    """Called when a connector's in_repeated_error_state changes."""
    try:
        CONNECTOR_IN_ERROR_STATE.labels(
            tenant_id=tenant_id,
            source=source,
            cc_pair_id=str(cc_pair_id),
            connector_name=connector_name,
        ).set(1.0 if in_error else 0.0)
    except Exception:
        logger.debug("Failed to record connector error state metric", exc_info=True)


def on_connector_indexing_success(
    tenant_id: str,
    source: str,
    cc_pair_id: int,
    connector_name: str,
    docs_indexed: int,
    success_timestamp: float,
) -> None:
    """Called when an indexing run completes successfully."""
    try:
        labels = {
            "tenant_id": tenant_id,
            "source": source,
            "cc_pair_id": str(cc_pair_id),
            "connector_name": connector_name,
        }
        CONNECTOR_LAST_SUCCESS_TIMESTAMP.labels(**labels).set(success_timestamp)
        if docs_indexed > 0:
            CONNECTOR_DOCS_INDEXED.labels(**labels).inc(docs_indexed)
    except Exception:
        logger.debug("Failed to record connector success metric", exc_info=True)
