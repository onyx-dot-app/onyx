"""Push-based Prometheus metrics for connector health and index attempts.

Emitted by workers at the point where state changes occur, rather than
pulled by scraping every tenant schema. This scales to any number of
tenants because each metric emission is O(1) — no schema iteration.

Metrics are emitted from:
- index_attempt.py mark_attempt_* functions (attempt status transitions)
- docprocessing/tasks.py _run_indexing (connector health updates)

All functions are safe to call from any context — they silently return
on failure to avoid disrupting the caller's business logic.
"""

from prometheus_client import Counter
from prometheus_client import Gauge

from onyx.utils.logger import setup_logger

logger = setup_logger()

# --- Index attempt lifecycle ---

INDEX_ATTEMPT_STATUS = Counter(
    "onyx_index_attempt_transitions_total",
    "Index attempt status transitions",
    ["tenant_id", "source", "cc_pair_id", "status"],
)

# --- Connector health ---

CONNECTOR_IN_ERROR_STATE = Gauge(
    "onyx_connector_in_error_state",
    "Whether the connector is in a repeated error state (1=yes, 0=no)",
    ["tenant_id", "source", "cc_pair_id"],
)

CONNECTOR_LAST_SUCCESS_TIMESTAMP = Gauge(
    "onyx_connector_last_success_timestamp_seconds",
    "Unix timestamp of last successful indexing for this connector",
    ["tenant_id", "source", "cc_pair_id"],
)

CONNECTOR_DOCS_INDEXED = Counter(
    "onyx_connector_docs_indexed_total",
    "Total documents indexed per connector (monotonic)",
    ["tenant_id", "source", "cc_pair_id"],
)

CONNECTOR_INDEXING_ERRORS = Counter(
    "onyx_connector_indexing_errors_total",
    "Total failed index attempts per connector (monotonic)",
    ["tenant_id", "source", "cc_pair_id"],
)


def on_index_attempt_status_change(
    tenant_id: str,
    source: str,
    cc_pair_id: int,
    status: str,
) -> None:
    """Called on any index attempt status transition.

    Active attempt count can be derived in PromQL from the transitions
    counter rather than using a Gauge with inc/dec, because inc and dec
    happen in different worker processes (docfetching vs docprocessing)
    which have separate prometheus_client state.
    """
    try:
        labels = {
            "tenant_id": tenant_id,
            "source": source,
            "cc_pair_id": str(cc_pair_id),
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
    in_error: bool,
) -> None:
    """Called when a connector's in_repeated_error_state changes."""
    try:
        CONNECTOR_IN_ERROR_STATE.labels(
            tenant_id=tenant_id,
            source=source,
            cc_pair_id=str(cc_pair_id),
        ).set(1.0 if in_error else 0.0)
    except Exception:
        logger.debug("Failed to record connector error state metric", exc_info=True)


def on_connector_indexing_success(
    tenant_id: str,
    source: str,
    cc_pair_id: int,
    docs_indexed: int,
    success_timestamp: float,
) -> None:
    """Called when an indexing run completes successfully."""
    try:
        labels = {
            "tenant_id": tenant_id,
            "source": source,
            "cc_pair_id": str(cc_pair_id),
        }
        CONNECTOR_LAST_SUCCESS_TIMESTAMP.labels(**labels).set(success_timestamp)
        if docs_indexed > 0:
            CONNECTOR_DOCS_INDEXED.labels(**labels).inc(docs_indexed)
    except Exception:
        logger.debug("Failed to record connector success metric", exc_info=True)
