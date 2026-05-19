"""Prometheus metrics for OpenSearch search latency, throughput, and errors.

Tracks client-side round-trip latency, server-side execution time (from
OpenSearch's ``took`` field), total search attempts, in-flight concurrency, and
per-error-type failure counts.

``onyx_opensearch_search_total`` counts attempts (incremented on entry to the
``track_opensearch_search`` context manager that wraps every request), so
``onyx_opensearch_search_errors_total / onyx_opensearch_search_total`` is a
meaningful failure rate.
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

# Tighter than the latency buckets because true network + serialization overhead
# is almost always sub-second.
_OVERHEAD_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
)

_client_server_overhead = Histogram(
    "onyx_opensearch_search_overhead_seconds",
    "Per-request overhead: client wall-clock duration minus server 'took'. Only "
    "sampled when both are known. Lets the dashboard compute proper quantiles instead of "
    "subtracting two independent quantile series.",
    ["search_type"],
    buckets=_OVERHEAD_BUCKETS,
)

_search_total = Counter(
    "onyx_opensearch_search_total",
    "Total number of OpenSearch search attempts (incremented before send, so this "
    "counts both successes and failures)",
    ["search_type"],
)

_search_errors = Counter(
    "onyx_opensearch_search_errors_total",
    "Total number of OpenSearch search attempts that errored, labeled by the error "
    "type",
    ["search_type", "error_type"],
)

_searches_in_progress = Gauge(
    "onyx_opensearch_searches_in_progress",
    "Number of OpenSearch searches currently in-flight",
    ["search_type"],
)


def record_opensearch_search_error(
    search_type: OpenSearchSearchType, exc: BaseException
) -> None:
    """Increments the search-error counter, labeled by exception class name."""
    try:
        _search_errors.labels(
            search_type=search_type.value, error_type=type(exc).__name__
        ).inc()
    except Exception:
        logger.warning(
            "Failed to record OpenSearch search error metric.", exc_info=True
        )


def observe_opensearch_search(
    search_type: OpenSearchSearchType,
    client_duration_s: float,
    server_took_ms: int | None,
) -> None:
    """
    Records latency histograms for a successfully-completed OpenSearch search.

    The attempt counter is incremented on entry to ``track_opensearch_search``
    so that failures count toward the denominator. This function should only be
    called on the success path.

    Args:
        search_type: The type of search.
        client_duration_s: Wall-clock duration measured on the client side, in
            seconds.
        server_took_ms: The ``took`` value from the OpenSearch response, in
            milliseconds. May be ``None`` if the response did not include it.
    """
    try:
        label = search_type.value
        _client_duration.labels(search_type=label).observe(client_duration_s)
        if server_took_ms is not None:
            server_duration_s = server_took_ms / 1000.0
            _server_duration.labels(search_type=label).observe(server_duration_s)
            overhead_s = client_duration_s - server_duration_s
            # Overhead cannot be negative. If it is we assume that there was an
            # error in timekeeping in OpenSearch, log a warning, and do not
            # include it in our histogram.
            if overhead_s < 0:
                logger.warning(
                    "OpenSearch search overhead is negative. Got a client duration "
                    "of %s seconds and a server 'took' of %s milliseconds. This is not possible. "
                    "Assuming there was an error in timekeeping in OpenSearch.",
                    client_duration_s,
                    server_took_ms,
                )
            else:
                _client_server_overhead.labels(search_type=label).observe(overhead_s)
    except Exception:
        logger.warning("Failed to record OpenSearch search metrics.", exc_info=True)


@contextmanager
def track_opensearch_search(
    search_type: OpenSearchSearchType,
) -> Generator[None, None, None]:
    """Wraps an OpenSearch search call.

    On entry: increments ``onyx_opensearch_search_total`` (the attempt
    counter) and ``onyx_opensearch_searches_in_progress`` (the in-flight
    gauge). On exit: decrements the gauge. Both increments are best-effort —
    a metrics failure must not break the underlying search.
    """
    label = search_type.value
    try:
        _search_total.labels(search_type=label).inc()
    except Exception:
        logger.warning(
            "Failed to record OpenSearch search attempt metric.", exc_info=True
        )
    incremented = False
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
