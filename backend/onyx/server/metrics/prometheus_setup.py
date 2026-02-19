"""Prometheus metrics setup for the Onyx API server.

Orchestrates HTTP request instrumentation via ``prometheus-fastapi-instrumentator``:
- Request count, latency histograms, in-progress gauges
- Pool checkout timeout exception handler
- Custom metric callbacks (e.g. slow request counting)

SQLAlchemy connection pool metrics are registered separately via
``setup_postgres_connection_pool_metrics`` during application lifespan
(after engines are created).
"""

from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.applications import Starlette

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

    instrumentator.add(slow_request_callback)

    instrumentator.instrument(app, latency_lowr_buckets=_LATENCY_BUCKETS).expose(app)
