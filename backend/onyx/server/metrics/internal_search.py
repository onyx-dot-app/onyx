"""Prometheus metrics for the internal search tool.

Tracks which retrieval lanes pass the query size check, the latency of that
check, and the latency of a whole search call. Labels carry no user text. The
admission counter carries a `tenant_id` label, so it shows which tenants send
oversized queries. The histograms describe the process and have no tenant label.
"""

import logging
from enum import Enum

from prometheus_client import Counter, Histogram

from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = logging.getLogger(__name__)


class QueryAdmission(str, Enum):
    """Outcome of the query size check for one retrieval lane."""

    # ASCII text short enough to run without analysis.
    SHORT = "short"
    ANALYZED = "analyzed"
    TOO_MANY_TERMS = "too_many_terms"
    TOO_LONG = "too_long"
    # The lane searches anyway.
    ANALYZER_FAILED = "analyzer_failed"


class SearchLane(str, Enum):
    # The lane's text is the user's message.
    USER_MESSAGE = "user_message"
    GENERATED = "generated"


class UserMessageSize(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


_query_admissions = Counter(
    "onyx_internal_search_query_admissions_total",
    "Retrieval lanes checked for query size, labeled by tenant, lane and outcome",
    ["tenant_id", "lane", "admission"],
)

_analyze_duration = Histogram(
    "onyx_internal_search_query_analyze_seconds",
    "Latency of the index analyzer request that counts a query's terms",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0),
)

_search_duration = Histogram(
    "onyx_internal_search_duration_seconds",
    "Latency of one internal search call, labeled by the user message size",
    ["user_message_size"],
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0),
)


def record_query_admission(lane: SearchLane, admission: QueryAdmission) -> None:
    try:
        _query_admissions.labels(
            tenant_id=CURRENT_TENANT_ID_CONTEXTVAR.get() or "unknown",
            lane=lane.value,
            admission=admission.value,
        ).inc()
    except Exception:
        logger.warning("Failed to record query admission metric.", exc_info=True)


def observe_query_analyze(duration_s: float) -> None:
    try:
        _analyze_duration.observe(duration_s)
    except Exception:
        logger.warning("Failed to record query analyze metric.", exc_info=True)


def observe_internal_search(
    user_message_size: UserMessageSize, duration_s: float
) -> None:
    try:
        _search_duration.labels(user_message_size=user_message_size.value).observe(
            duration_s
        )
    except Exception:
        logger.warning("Failed to record internal search metric.", exc_info=True)
