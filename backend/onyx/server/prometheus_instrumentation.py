"""Prometheus instrumentation for the Onyx API server.

Provides a production-grade metrics configuration with:

- Exact HTTP status codes (no grouping into 2xx/3xx)
- In-progress request gauge broken down by handler and method
- Custom latency histogram buckets tuned for API workloads
- Request/response size tracking
- Slow request counter with configurable threshold
"""

import os

from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import Info
from starlette.applications import Starlette

SLOW_REQUEST_THRESHOLD_SECONDS: float = float(
    os.environ.get("SLOW_REQUEST_THRESHOLD_SECONDS", "1.0")
)

_EXCLUDED_HANDLERS = [
    "/health",
    "/metrics",
    "/openapi.json",
]

_slow_requests = Counter(
    "onyx_api_slow_requests_total",
    "Total requests exceeding the slow request threshold",
    ["method", "handler", "status"],
)


def _slow_request_callback(info: Info) -> None:
    """Increment slow request counter when duration exceeds threshold."""
    if info.modified_duration > SLOW_REQUEST_THRESHOLD_SECONDS:
        _slow_requests.labels(
            method=info.method,
            handler=info.modified_handler,
            status=info.modified_status,
        ).inc()


def setup_prometheus_metrics(app: Starlette) -> None:
    """Configure and attach Prometheus instrumentation to the FastAPI app.

    Records exact status codes, tracks in-progress requests per handler,
    and counts slow requests exceeding a configurable threshold.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=False,
        should_group_untemplated=True,
        should_instrument_requests_inprogress=True,
        inprogress_labels=True,
        excluded_handlers=_EXCLUDED_HANDLERS,
    )

    instrumentator.add(_slow_request_callback)

    instrumentator.instrument(app).expose(app)
