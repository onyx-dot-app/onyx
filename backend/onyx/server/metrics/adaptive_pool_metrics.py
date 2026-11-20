"""Prometheus metrics for adaptive worker pools (``AdaptiveConcurrency``).

``pool`` is a short fixed name that the code gives the pool, for example
``drive_listing``. Pools with the same name in one process share the series.
"""

from prometheus_client import Counter, Gauge

ADAPTIVE_POOL_LIMIT = Gauge(
    "onyx_adaptive_pool_limit",
    "The worker limit of an adaptive pool",
    ["pool"],
)

ADAPTIVE_POOL_IN_FLIGHT = Gauge(
    "onyx_adaptive_pool_in_flight",
    "Tasks that an adaptive pool runs now",
    ["pool"],
)

ADAPTIVE_POOL_CUTS = Counter(
    "onyx_adaptive_pool_cuts_total",
    "Times an adaptive pool halved its worker limit after pushback",
    ["pool"],
)

ADAPTIVE_POOL_GROWS = Counter(
    "onyx_adaptive_pool_grows_total",
    "Times an adaptive pool added one worker to its limit",
    ["pool"],
)


def record_pool_state(pool: str, limit: int, in_flight: int) -> None:
    ADAPTIVE_POOL_LIMIT.labels(pool=pool).set(limit)
    ADAPTIVE_POOL_IN_FLIGHT.labels(pool=pool).set(in_flight)


def record_pool_cut(pool: str) -> None:
    ADAPTIVE_POOL_CUTS.labels(pool=pool).inc()


def record_pool_grow(pool: str) -> None:
    ADAPTIVE_POOL_GROWS.labels(pool=pool).inc()
