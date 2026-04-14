"""Connector-deletion-specific Prometheus metrics.

Tracks the deletion lifecycle:
  1. Deletions started (taskset generated)
  2. Deletions completed (success or failure)
  3. Taskset duration (from taskset generation to completion or failure).
     Note: this measures the most recent taskset execution, NOT wall-clock
     time since the user triggered the deletion. When deletion is blocked by
     indexing/pruning/permissions, the fence is cleared and a fresh taskset
     is generated on each retry, resetting this timer.
  4. Deletion blocked by dependencies (indexing, pruning, permissions, etc.)
  5. Fence resets (stuck deletion recovery)

All metrics are labeled by tenant_id. cc_pair_id is intentionally excluded
to avoid unbounded cardinality.

Usage:
    from onyx.server.metrics.deletion_metrics import (
        inc_deletion_started,
        inc_deletion_completed,
        observe_deletion_taskset_duration,
        inc_deletion_blocked,
        inc_deletion_fence_reset,
    )
"""

from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.utils.logger import setup_logger

logger = setup_logger()

DELETION_STARTED = Counter(
    "onyx_deletion_started_total",
    "Connector deletions initiated (taskset generated)",
    ["tenant_id"],
)

DELETION_COMPLETED = Counter(
    "onyx_deletion_completed_total",
    "Connector deletions completed",
    ["tenant_id", "outcome"],
)

DELETION_TASKSET_DURATION = Histogram(
    "onyx_deletion_taskset_duration_seconds",
    "Duration of a connector deletion taskset, from taskset generation "
    "to completion or failure. Does not include time spent blocked on "
    "indexing/pruning/permissions before the taskset was generated.",
    ["tenant_id", "outcome"],
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600],
)

DELETION_BLOCKED = Counter(
    "onyx_deletion_blocked_total",
    "Times deletion was blocked by a dependency",
    ["tenant_id", "blocker"],
)

DELETION_FENCE_RESET = Counter(
    "onyx_deletion_fence_reset_total",
    "Deletion fences reset due to missing celery tasks",
    ["tenant_id"],
)


def inc_deletion_started(tenant_id: str) -> None:
    try:
        DELETION_STARTED.labels(tenant_id=tenant_id).inc()
    except Exception:
        logger.debug("Failed to record deletion started", exc_info=True)


def inc_deletion_completed(tenant_id: str, outcome: str) -> None:
    try:
        DELETION_COMPLETED.labels(tenant_id=tenant_id, outcome=outcome).inc()
    except Exception:
        logger.debug("Failed to record deletion completed", exc_info=True)


def observe_deletion_taskset_duration(
    tenant_id: str, outcome: str, duration_seconds: float
) -> None:
    try:
        DELETION_TASKSET_DURATION.labels(tenant_id=tenant_id, outcome=outcome).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record deletion taskset duration", exc_info=True)


def inc_deletion_blocked(tenant_id: str, blocker: str) -> None:
    try:
        DELETION_BLOCKED.labels(tenant_id=tenant_id, blocker=blocker).inc()
    except Exception:
        logger.debug("Failed to record deletion blocked", exc_info=True)


def inc_deletion_fence_reset(tenant_id: str) -> None:
    try:
        DELETION_FENCE_RESET.labels(tenant_id=tenant_id).inc()
    except Exception:
        logger.debug("Failed to record deletion fence reset", exc_info=True)
