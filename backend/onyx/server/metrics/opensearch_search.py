"""Prometheus metrics for OpenSearch search latency and throughput.

Tracks client-side round-trip latency, server-side execution time (from
OpenSearch's ``took`` field), total search count, and in-flight concurrency.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram

from onyx.document_index.opensearch.constants import OpenSearchSearchType

logger = logging.getLogger(__name__)

_SEARCH_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
)

_client_duration = Histogram(
    "onyx_opensearch_search_client_duration_seconds",
    "Client-side end-to-end latency of OpenSearch search calls",
    ["search_type"],
    buckets=_SEARCH_LATENCY_BUCKETS,
)

_server_duration = Histogram(
    "onyx_opensearch_search_server_duration_seconds",
    "Server-side execution time reported by OpenSearch (took field)",
    ["search_type"],
    buckets=_SEARCH_LATENCY_BUCKETS,
)

_search_total = Counter(
    "onyx_opensearch_search_total",
    "Total number of search requests sent to OpenSearch",
    ["search_type"],
)

_searches_in_progress = Gauge(
    "onyx_opensearch_searches_in_progress",
    "Number of OpenSearch searches currently in-flight",
    ["search_type"],
)


def observe_opensearch_search(
    search_type: OpenSearchSearchType,
    client_duration_s: float,
    server_took_ms: int | None,
) -> None:
    """Records latency and throughput metrics for a completed OpenSearch search.

    Args:
        search_type: The type of search.
        client_duration_s: Wall-clock duration measured on the client side, in
            seconds.
        server_took_ms: The ``took`` value from the OpenSearch response, in
            milliseconds. May be ``None`` if the response did not include it.
    """
    try:
        label = search_type.value
        _search_total.labels(search_type=label).inc()
        _client_duration.labels(search_type=label).observe(client_duration_s)
        if server_took_ms is not None:
            _server_duration.labels(search_type=label).observe(server_took_ms / 1000.0)
    except Exception:
        logger.warning("Failed to record OpenSearch search metrics.", exc_info=True)


@contextmanager
def track_opensearch_search_in_progress(
    search_type: OpenSearchSearchType,
) -> Generator[None, None, None]:
    """Context manager that tracks in-flight OpenSearch searches via a Gauge."""
    incremented = False
    label = search_type.value
    try:
        _searches_in_progress.labels(search_type=label).inc()
        incremented = True
    except Exception:
        logger.warning("Failed to increment in-progress search gauge.", exc_info=True)
    try:
        yield
    finally:
        if incremented:
            try:
                _searches_in_progress.labels(search_type=label).dec()
            except Exception:
                logger.warning(
                    "Failed to decrement in-progress search gauge.", exc_info=True
                )
