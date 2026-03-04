"""Per-endpoint memory delta middleware.

Measures RSS change before and after each HTTP request, attributing
memory growth to specific route handlers. Uses psutil for a single
syscall per request (sub-microsecond overhead).

Metrics:
- onyx_api_request_rss_delta_bytes: Histogram of RSS change per request
- onyx_api_process_rss_bytes: Gauge of current process RSS
"""

import re
from collections.abc import Awaitable
from collections.abc import Callable

import psutil
from fastapi import FastAPI
from fastapi import Request
from fastapi.routing import APIRoute
from prometheus_client import Gauge
from prometheus_client import Histogram
from starlette.responses import Response

_RSS_DELTA = Histogram(
    "onyx_api_request_rss_delta_bytes",
    "RSS change in bytes during a single request",
    ["handler"],
    buckets=(
        -16777216,
        -1048576,
        -65536,
        0,
        1024,
        4096,
        16384,
        65536,
        262144,
        1048576,
        4194304,
        16777216,
    ),
)

_PROCESS_RSS = Gauge(
    "onyx_api_process_rss_bytes",
    "Current process RSS in bytes",
)

_process = psutil.Process()


def _build_route_map(app: FastAPI) -> list[tuple[re.Pattern[str], str]]:
    route_map: list[tuple[re.Pattern[str], str]] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            route_map.append((route.path_regex, route.path))
    return route_map


def _match_route(route_map: list[tuple[re.Pattern[str], str]], path: str) -> str | None:
    for pattern, template in route_map:
        if pattern.match(path):
            return template
    return None


def add_memory_delta_middleware(app: FastAPI) -> None:
    """Register middleware that tracks per-endpoint RSS deltas.

    Builds its own route map to avoid contextvar ordering issues
    with the endpoint context middleware.
    """
    route_map = _build_route_map(app)

    @app.middleware("http")
    async def memory_delta_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        handler = _match_route(route_map, request.url.path) or "unmatched"
        rss_before = _process.memory_info().rss

        response = await call_next(request)

        rss_after = _process.memory_info().rss
        delta = rss_after - rss_before
        _RSS_DELTA.labels(handler=handler).observe(delta)
        _PROCESS_RSS.set(rss_after)

        return response
