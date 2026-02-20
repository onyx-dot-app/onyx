"""Slow request counter metric.

Increments a counter whenever a request exceeds a configurable duration
threshold. Useful for identifying endpoints that regularly take too long.
"""

import os

from prometheus_client import Counter
from prometheus_fastapi_instrumentator.metrics import Info

SLOW_REQUEST_THRESHOLD_SECONDS: float = max(
    0.0,
    float(os.environ.get("SLOW_REQUEST_THRESHOLD_SECONDS", "1.0")),
)

_slow_requests = Counter(
    "onyx_api_slow_requests_total",
    "Total requests exceeding the slow request threshold",
    ["method", "handler", "status"],
)


def slow_request_callback(info: Info) -> None:
    """Increment slow request counter when duration exceeds threshold."""
    if info.modified_duration > SLOW_REQUEST_THRESHOLD_SECONDS:
        _slow_requests.labels(
            method=info.method,
            handler=info.modified_handler,
            status=info.modified_status,
        ).inc()
