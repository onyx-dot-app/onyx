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

import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry, PoolProxiedConnection, QueuePool

from onyx.db.engine.async_sql_engine import async_engine_hooks
from onyx.db.engine.shard_registry import is_default_shard, shard_engine_hooks
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_ENDPOINT_CONTEXTVAR,
    CURRENT_TENANT_ID_CONTEXTVAR,
)

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
    ["handler", "engine", "tenant_id"],
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
        self._lock = threading.Lock()

    def add_pool(self, label: str, pool: QueuePool) -> None:
        # Shard engines register from request threads while scrapes iterate.
        # Upsert by label: a rebuilt engine replaces its disposed pool.
        with self._lock:
            self._pools = [(lb, pl) for lb, pl in self._pools if lb != label]
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

        with self._lock:
            pools = list(self._pools)
        for label, pool in pools:
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
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get() or "unknown"
        conn_record.info["_metrics_endpoint"] = handler
        conn_record.info["_metrics_tenant_id"] = tenant_id
        conn_record.info["_metrics_checkout_time"] = time.monotonic()
        _checkout_total.labels(engine=label).inc()
        _connections_held.labels(
            handler=handler, engine=label, tenant_id=tenant_id
        ).inc()

    @event.listens_for(engine, "checkin")
    def on_checkin(
        dbapi_conn: DBAPIConnection,  # noqa: ARG001
        conn_record: ConnectionPoolEntry,
    ) -> None:
        handler = conn_record.info.pop("_metrics_endpoint", None)
        tenant_id = conn_record.info.pop("_metrics_tenant_id", "unknown")
        start = conn_record.info.pop("_metrics_checkout_time", None)
        _checkin_total.labels(engine=label).inc()
        # A connection checked out before the listeners attached (engine built
        # while registration raced) carries no marker; decrementing would leave
        # the gauge negative forever.
        if handler is not None:
            _connections_held.labels(
                handler=handler, engine=label, tenant_id=tenant_id
            ).dec()
        if start is not None:
            _hold_seconds.labels(handler=handler or "unknown", engine=label).observe(
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
        tenant_id = conn_record.info.pop("_metrics_tenant_id", "unknown")
        start = conn_record.info.pop("_metrics_checkout_time", None)
        if handler:
            _connections_held.labels(
                handler=handler, engine=label, tenant_id=tenant_id
            ).dec()
        if start is not None:
            _hold_seconds.labels(handler=handler or "unknown", engine=label).observe(
                time.monotonic() - start
            )


_collector = PoolStateCollector()
# Label -> the engine registered under it. Holding the Engine (not just an id)
# makes the identity check safe against id reuse after garbage collection, and
# lets a rebuilt engine (reset flows) replace its predecessor's registration.
_registered_engines: dict[str, Engine] = {}
_registration_lock = threading.Lock()
_collector_registered = False


def _register_engine_pool(label: str, engine: Engine | AsyncEngine) -> None:
    """Register one engine's pool with the shared collector.

    Repeated calls for the same engine are no-ops (the hooks deliver
    at-least-once); a different engine under a known label replaces the stale
    registration. Engines using NullPool report lifecycle events only.
    For AsyncEngine, events are registered on the underlying sync_engine.
    """
    sync_engine_for_identity = (
        engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    )
    with _registration_lock:
        if _registered_engines.get(label) is sync_engine_for_identity:
            return
        _registered_engines[label] = sync_engine_for_identity

    sync_engine = sync_engine_for_identity
    pool = sync_engine.pool

    # Lifecycle events fire for every pool class. Under NullPool (external
    # pooler deployments) they are the only app-side connection metrics.
    _register_pool_events(sync_engine, label)

    if isinstance(pool, QueuePool):
        _collector.add_pool(label, pool)
        logger.info("Registered pool metrics for engine '%s'", label)
    else:
        logger.info(
            "Registered pool lifecycle metrics for engine '%s' (%s has no pool state)",
            label,
            type(pool).__name__,
        )


def setup_postgres_connection_pool_metrics(
    engines: dict[str, Engine | AsyncEngine],
) -> None:
    """Register pool metrics for the provided engines and all shard engines.

    ``engines`` maps labels to the default shard's engines (e.g. ``sync``,
    ``async``, ``readonly``). Lazily-created shard engines register through the
    engine-creation hooks under ``sync_<shard>`` / ``async_<shard>``.
    """

    def register_async_shard(shard: str, engine: AsyncEngine) -> None:
        # The default async engine registers above under its historical label.
        if not is_default_shard(shard):
            _register_engine_pool(f"async_{shard}", engine)

    for label, engine in engines.items():
        _register_engine_pool(label, engine)

    shard_engine_hooks.subscribe(
        lambda shard, engine: _register_engine_pool(f"sync_{shard}", engine)
    )
    async_engine_hooks.subscribe(register_async_shard)

    global _collector_registered
    with _registration_lock:
        first_setup = not _collector_registered
        _collector_registered = True
    if first_setup:
        REGISTRY.register(_collector)
