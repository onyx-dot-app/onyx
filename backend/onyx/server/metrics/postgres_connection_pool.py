"""SQLAlchemy connection pool Prometheus metrics.

Provides production-grade visibility into database connection pool state:

- Pool state gauges (checked-out, idle, overflow, configured size)
- Pool lifecycle counters (checkouts, checkins, creates, invalidations, timeouts)
- Per-endpoint connection attribution (which endpoints hold connections, for how long)

Metrics are collected via two mechanisms:
1. A custom Prometheus Collector that reads pool snapshots on each /metrics scrape
2. SQLAlchemy pool event listeners (checkout, checkin, connect, invalidate) for
   counters, histograms, and attribution
"""

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_client.registry import REGISTRY
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.pool import PoolProxiedConnection
from sqlalchemy.pool import QueuePool

from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_ENDPOINT_CONTEXTVAR

logger = setup_logger()

# --- Pool lifecycle counters (event-driven) ---

_checkout_total = Counter(
    "onyx_db_pool_checkout_total",
    "Total connection checkouts from the pool",
    ["engine"],
)

_checkin_total = Counter(
    "onyx_db_pool_checkin_total",
    "Total connection checkins to the pool",
    ["engine"],
)

_connections_created_total = Counter(
    "onyx_db_pool_connections_created_total",
    "Total new database connections created",
    ["engine"],
)

_invalidations_total = Counter(
    "onyx_db_pool_invalidations_total",
    "Total connection invalidations",
    ["engine"],
)

_checkout_timeout_total = Counter(
    "onyx_db_pool_checkout_timeout_total",
    "Total connection checkout timeouts",
    ["engine"],
)

# --- Per-endpoint attribution (event-driven) ---

_connections_held = Gauge(
    "onyx_db_connections_held_by_endpoint",
    "Number of DB connections currently held, by endpoint and engine",
    ["handler", "engine"],
)

_hold_seconds = Histogram(
    "onyx_db_connection_hold_seconds",
    "Duration a DB connection is held by an endpoint",
    ["handler", "engine"],
)


def pool_timeout_handler(
    request: Request,  # noqa: ARG001
    exc: Exception,
) -> JSONResponse:
    """Increment the checkout timeout counter and return 503."""
    _checkout_timeout_total.labels(engine="unknown").inc()
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database connection pool timeout",
            "error": str(exc),
        },
    )


class PoolStateCollector(Collector):
    """Custom Prometheus collector that reads QueuePool state on each scrape.

    Uses pool.checkedout(), pool.checkedin(), pool.overflow(), and pool.size()
    for an atomic snapshot of pool state. Registered engines are stored as
    (label, pool) tuples to avoid holding references to the full Engine.
    """

    def __init__(self) -> None:
        self._pools: list[tuple[str, QueuePool]] = []

    def add_pool(self, label: str, pool: QueuePool) -> None:
        self._pools.append((label, pool))

    def collect(self) -> list[GaugeMetricFamily]:
        checked_out = GaugeMetricFamily(
            "onyx_db_pool_checked_out",
            "Currently checked-out connections",
            labels=["engine"],
        )
        checked_in = GaugeMetricFamily(
            "onyx_db_pool_checked_in",
            "Idle connections available in the pool",
            labels=["engine"],
        )
        overflow = GaugeMetricFamily(
            "onyx_db_pool_overflow",
            "Current overflow connections beyond pool_size",
            labels=["engine"],
        )
        size = GaugeMetricFamily(
            "onyx_db_pool_size",
            "Configured pool size",
            labels=["engine"],
        )

        for label, pool in self._pools:
            checked_out.add_metric([label], pool.checkedout())
            checked_in.add_metric([label], pool.checkedin())
            overflow.add_metric([label], pool.overflow())
            size.add_metric([label], pool.size())

        return [checked_out, checked_in, overflow, size]

    def describe(self) -> list[GaugeMetricFamily]:
        # Return empty to mark this as an "unchecked" collector. Prometheus
        # skips upfront descriptor validation and just calls collect() at
        # scrape time. Required because our metrics are dynamic (engine
        # labels depend on which engines are registered at runtime).
        return []


def _register_pool_events(engine: Engine, label: str) -> None:
    """Attach pool event listeners for metrics collection.

    Listens to checkout, checkin, connect, and invalidate events.
    Stores per-connection metadata on connection_record.info for attribution.
    """

    @event.listens_for(engine, "checkout")
    def on_checkout(
        dbapi_conn: DBAPIConnection,  # noqa: ARG001
        conn_record: ConnectionPoolEntry,
        conn_proxy: PoolProxiedConnection,  # noqa: ARG001
    ) -> None:
        handler = CURRENT_ENDPOINT_CONTEXTVAR.get() or "unknown"
        conn_record.info["_metrics_endpoint"] = handler
        conn_record.info["_metrics_checkout_time"] = time.monotonic()
        _checkout_total.labels(engine=label).inc()
        _connections_held.labels(handler=handler, engine=label).inc()

    @event.listens_for(engine, "checkin")
    def on_checkin(
        dbapi_conn: DBAPIConnection,  # noqa: ARG001
        conn_record: ConnectionPoolEntry,
    ) -> None:
        handler = conn_record.info.pop("_metrics_endpoint", "unknown")
        start = conn_record.info.pop("_metrics_checkout_time", None)
        _checkin_total.labels(engine=label).inc()
        _connections_held.labels(handler=handler, engine=label).dec()
        if start is not None:
            _hold_seconds.labels(handler=handler, engine=label).observe(
                time.monotonic() - start
            )

    @event.listens_for(engine, "connect")
    def on_connect(
        dbapi_conn: DBAPIConnection,  # noqa: ARG001
        conn_record: ConnectionPoolEntry,  # noqa: ARG001
    ) -> None:
        _connections_created_total.labels(engine=label).inc()

    @event.listens_for(engine, "invalidate")
    def on_invalidate(
        dbapi_conn: DBAPIConnection,  # noqa: ARG001
        conn_record: ConnectionPoolEntry,
        exception: BaseException | None,  # noqa: ARG001
    ) -> None:
        _invalidations_total.labels(engine=label).inc()
        # Defensively clean up the held-connections gauge in case checkin
        # doesn't fire after invalidation (e.g. hard pool shutdown).
        handler = conn_record.info.pop("_metrics_endpoint", None)
        start = conn_record.info.pop("_metrics_checkout_time", None)
        if handler:
            _connections_held.labels(handler=handler, engine=label).dec()
        if start is not None:
            _hold_seconds.labels(handler=handler or "unknown", engine=label).observe(
                time.monotonic() - start
            )


def setup_postgres_connection_pool_metrics(
    engines: dict[str, Engine | AsyncEngine],
) -> None:
    """Register pool metrics for all provided engines.

    Args:
        engines: Mapping of engine label to Engine or AsyncEngine.
            Example: {"sync": sync_engine, "async": async_engine, "readonly": ro_engine}

    Engines using NullPool are skipped (no pool state to monitor).
    For AsyncEngine, events are registered on the underlying sync_engine.
    """
    collector = PoolStateCollector()

    for label, engine in engines.items():
        # Resolve async engines to their underlying sync engine
        sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine

        pool = sync_engine.pool
        if not isinstance(pool, QueuePool):
            logger.info(
                f"Skipping pool metrics for engine '{label}' "
                f"({type(pool).__name__} — no pool state)"
            )
            continue

        collector.add_pool(label, pool)
        _register_pool_events(sync_engine, label)
        logger.info(f"Registered pool metrics for engine '{label}'")

    REGISTRY.register(collector)
