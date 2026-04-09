"""Pruning-specific Prometheus metrics.

Tracks three pruning pipeline phases for connector_pruning_generator_task:
  1. Document ID enumeration duration (extract_ids_from_runnable_connector)
  2. Diff + dispatch duration (DB lookup, set diff, generate_tasks)
  3. Rate limit errors during enumeration

All metrics are labeled by connector_type to identify which connector sources
are the most expensive to prune. cc_pair_id is intentionally excluded to avoid
unbounded cardinality.

Usage:
    from onyx.server.metrics.pruning_metrics import (
        observe_pruning_enumeration_duration,
        observe_pruning_diff_duration,
        inc_pruning_rate_limit_error,
    )
"""

from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.utils.logger import setup_logger

logger = setup_logger()

PRUNING_ENUMERATION_DURATION = Histogram(
    "onyx_pruning_enumeration_duration_seconds",
    "Duration of document ID enumeration from the source connector during pruning",
    ["connector_type"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)

PRUNING_DIFF_DURATION = Histogram(
    "onyx_pruning_diff_duration_seconds",
    "Duration of diff computation and subtask dispatch during pruning",
    ["connector_type"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)

PRUNING_RATE_LIMIT_ERRORS = Counter(
    "onyx_pruning_rate_limit_errors_total",
    "Total rate limit errors encountered during pruning document ID enumeration",
    ["connector_type"],
)


def observe_pruning_enumeration_duration(
    duration_seconds: float, connector_type: str
) -> None:
    try:
        PRUNING_ENUMERATION_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record pruning enumeration duration", exc_info=True)


def observe_pruning_diff_duration(duration_seconds: float, connector_type: str) -> None:
    try:
        PRUNING_DIFF_DURATION.labels(connector_type=connector_type).observe(
            duration_seconds
        )
    except Exception:
        logger.debug("Failed to record pruning diff duration", exc_info=True)


def inc_pruning_rate_limit_error(connector_type: str) -> None:
    try:
        PRUNING_RATE_LIMIT_ERRORS.labels(connector_type=connector_type).inc()
    except Exception:
        logger.debug("Failed to record pruning rate limit error", exc_info=True)
