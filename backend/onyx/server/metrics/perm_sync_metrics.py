"""Permission-sync-specific Prometheus metrics.

Tracks doc permission sync and external group sync phases:

Doc permission sync (connector_permission_sync_generator_task):
  1. Overall sync duration (source enumeration + DB updates)
  2. Cumulative per-element DB update duration within update_db
  3. Documents successfully synced
  4. Documents with permission errors

External group sync (_perform_external_group_sync):
  1. Overall sync duration
  2. Cumulative batch upsert duration
  3. Groups processed
  4. Unique users discovered
  5. Errors encountered

All metrics are labeled by connector_type to identify which connector sources
are the most expensive to sync. cc_pair_id is intentionally excluded to avoid
unbounded cardinality.

Usage:
    from onyx.server.metrics.perm_sync_metrics import (
        observe_doc_perm_sync_duration,
        observe_doc_perm_sync_db_update_duration,
        inc_doc_perm_sync_docs_processed,
        inc_doc_perm_sync_errors,
        observe_group_sync_duration,
        observe_group_sync_upsert_duration,
        inc_group_sync_groups_processed,
        inc_group_sync_users_processed,
        inc_group_sync_errors,
    )
"""

from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.utils.logger import setup_logger

logger = setup_logger()

# --- Doc permission sync metrics ---

DOC_PERM_SYNC_DURATION = Histogram(
    "onyx_doc_perm_sync_duration_seconds",
    "Overall duration of doc permission sync (source enumeration + DB updates)",
    ["connector_type"],
    buckets=[5, 60, 600, 1800, 3600, 10800, 21600],
)

DOC_PERM_SYNC_DB_UPDATE_DURATION = Histogram(
    "onyx_doc_perm_sync_db_update_duration_seconds",
    "Cumulative per-element DB update duration within a single doc permission sync",
    ["connector_type"],
    buckets=[0.1, 0.5, 1, 5, 15, 30, 60, 300, 600],
)

DOC_PERM_SYNC_DOCS_PROCESSED = Counter(
    "onyx_doc_perm_sync_docs_processed_total",
    "Total documents successfully synced during doc permission sync",
    ["connector_type"],
)

DOC_PERM_SYNC_ERRORS = Counter(
    "onyx_doc_perm_sync_errors_total",
    "Total document permission errors during doc permission sync",
    ["connector_type"],
)

# --- External group sync metrics ---

GROUP_SYNC_DURATION = Histogram(
    "onyx_group_sync_duration_seconds",
    "Overall duration of external group sync",
    ["connector_type"],
    buckets=[5, 60, 600, 1800, 3600, 10800, 21600],
)

GROUP_SYNC_UPSERT_DURATION = Histogram(
    "onyx_group_sync_upsert_duration_seconds",
    "Cumulative batch upsert duration within a single external group sync",
    ["connector_type"],
    buckets=[0.1, 0.5, 1, 5, 15, 30, 60, 300, 600],
)

GROUP_SYNC_GROUPS_PROCESSED = Counter(
    "onyx_group_sync_groups_processed_total",
    "Total groups processed during external group sync",
    ["connector_type"],
)

GROUP_SYNC_USERS_PROCESSED = Counter(
    "onyx_group_sync_users_processed_total",
    "Total unique users discovered during external group sync",
    ["connector_type"],
)

GROUP_SYNC_ERRORS = Counter(
    "onyx_group_sync_errors_total",
    "Total errors during external group sync",
    ["connector_type"],
)


# --- Doc permission sync helpers ---


def observe_doc_perm_sync_duration(
    duration_seconds: float, connector_type: str
) -> None:
    try:
        DOC_PERM_SYNC_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record doc perm sync duration", exc_info=True)


def observe_doc_perm_sync_db_update_duration(
    duration_seconds: float, connector_type: str
) -> None:
    try:
        DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record doc perm sync db update duration", exc_info=True)


def inc_doc_perm_sync_docs_processed(connector_type: str, amount: int = 1) -> None:
    try:
        DOC_PERM_SYNC_DOCS_PROCESSED.labels(connector_type=connector_type).inc(amount)
    except Exception:
        logger.debug("Failed to record doc perm sync docs processed", exc_info=True)


def inc_doc_perm_sync_errors(connector_type: str, amount: int = 1) -> None:
    try:
        DOC_PERM_SYNC_ERRORS.labels(connector_type=connector_type).inc(amount)
    except Exception:
        logger.debug("Failed to record doc perm sync errors", exc_info=True)


# --- External group sync helpers ---


def observe_group_sync_duration(duration_seconds: float, connector_type: str) -> None:
    try:
        GROUP_SYNC_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record group sync duration", exc_info=True)


def observe_group_sync_upsert_duration(
    duration_seconds: float, connector_type: str
) -> None:
    try:
        GROUP_SYNC_UPSERT_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record group sync upsert duration", exc_info=True)


def inc_group_sync_groups_processed(connector_type: str, amount: int = 1) -> None:
    try:
        GROUP_SYNC_GROUPS_PROCESSED.labels(connector_type=connector_type).inc(amount)
    except Exception:
        logger.debug("Failed to record group sync groups processed", exc_info=True)


def inc_group_sync_users_processed(connector_type: str, amount: int = 1) -> None:
    try:
        GROUP_SYNC_USERS_PROCESSED.labels(connector_type=connector_type).inc(amount)
    except Exception:
        logger.debug("Failed to record group sync users processed", exc_info=True)


def inc_group_sync_errors(connector_type: str, amount: int = 1) -> None:
    try:
        GROUP_SYNC_ERRORS.labels(connector_type=connector_type).inc(amount)
    except Exception:
        logger.debug("Failed to record group sync errors", exc_info=True)
