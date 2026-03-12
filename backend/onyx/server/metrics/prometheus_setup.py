"""Prometheus metrics setup for the Onyx API server.

Central orchestration point for ALL metrics and observability.

Functions:
- ``setup_prometheus_metrics(app)`` — HTTP request instrumentation (middleware).
  Called from ``get_application()``.
- ``setup_app_observability(app)`` — app-scoped observability (middleware that
  must be registered after all routers). Called from ``get_application()``.

SQLAlchemy connection pool metrics are registered separately via
``setup_postgres_connection_pool_metrics`` during application lifespan
(after engines are created).
"""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import default as default_metrics
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.applications import Starlette

from onyx.server.metrics.per_tenant import per_tenant_request_callback
from onyx.server.metrics.postgres_connection_pool import pool_timeout_handler
from onyx.server.metrics.slow_requests import slow_request_callback

_EXCLUDED_HANDLERS = [
    "/health",
    "/metrics",
    "/openapi.json",
]

# Denser buckets for per-handler latency histograms. The instrumentator's
# default (0.1, 0.5, 1) is too coarse for meaningful P95/P99 computation.
_LATENCY_BUCKETS = (
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
)


def setup_prometheus_metrics(app: Starlette) -> None:
    """Initialize HTTP request metrics for the Onyx API server.

    Must be called in ``get_application()`` BEFORE the app starts, because
    the instrumentator adds middleware via ``app.add_middleware()``.

    Args:
        app: The FastAPI/Starlette application to instrument.
    """
    app.add_exception_handler(SATimeoutError, pool_timeout_handler)

    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=False,
        should_group_untemplated=True,
        should_instrument_requests_inprogress=True,
        inprogress_labels=True,
        excluded_handlers=_EXCLUDED_HANDLERS,
    )

    # Explicitly create the default metrics (http_requests_total,
    # http_request_duration_seconds, etc.) and add them first.  The library
    # skips creating defaults when ANY custom instrumentations are registered
    # via .add(), so we must include them ourselves.
    default_callback = default_metrics(latency_lowr_buckets=_LATENCY_BUCKETS)
    if default_callback:
        instrumentator.add(default_callback)

    instrumentator.add(slow_request_callback)
    instrumentator.add(per_tenant_request_callback)

    instrumentator.instrument(app, latency_lowr_buckets=_LATENCY_BUCKETS).expose(app)


def setup_app_observability(app: FastAPI) -> None:
    """Register app-scoped observability components.

    Must be called in ``get_application()`` AFTER all routers are registered
    (memory delta middleware builds its route map at registration time).

    Args:
        app: The FastAPI application.
    """
    from onyx.server.metrics.memory_delta import add_memory_delta_middleware

    add_memory_delta_middleware(app)


def start_observability() -> None:
    """Start lifespan-scoped observability probes and collectors.

    Called from ``lifespan()`` after engines/pools are ready.
    """
    from onyx.server.metrics.event_loop_lag import start_event_loop_lag_probe
    from onyx.server.metrics.redis_connection_pool import (
        setup_redis_connection_pool_metrics,
    )

    setup_redis_connection_pool_metrics()
    start_event_loop_lag_probe()


async def stop_observability() -> None:
    """Shut down lifespan-scoped observability probes.

    Called from ``lifespan()`` after yield, before engine teardown.
    """
    from onyx.server.metrics.event_loop_lag import stop_event_loop_lag_probe

    await stop_event_loop_lag_probe()
