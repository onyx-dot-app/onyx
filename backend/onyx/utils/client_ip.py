"""Extract the real client IP from a FastAPI request and expose it per-request.

nginx-ingress forwards the real client address in ``X-Forwarded-For`` while
``request.client.host`` is the in-cluster proxy address. Callers use this for
rate limiting, PostHog ``$ip`` enrichment (drives GeoIP), and abuse attribution.

Only globally-routable addresses are returned so private/loopback/link-local
values (pod-to-pod hops, localhost) never leak into downstream systems as
though they were the client.

``ClientIPMiddleware`` stashes the per-request IP into a ``ContextVar`` so
deep-stack telemetry / audit-log calls can read it via ``current_client_ip()``
without threading a ``Request`` through every call site. The contextvar is
request-scoped (token reset in a ``finally`` block) and copies cleanly into
threadpool handoffs that use ``contextvars.copy_context()``.
"""

import ipaddress
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

_CLIENT_IP_CONTEXTVAR: ContextVar[str | None] = ContextVar(
    "onyx_client_ip", default=None
)


def _is_globally_routable(ip_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str).is_global
    except ValueError:
        return False


def get_client_ip(request: Request) -> str | None:
    """Walk ``X-Forwarded-For`` right-to-left and return the first globally
    routable address. Proxies append their immediate peer at the right of
    XFF, so the rightmost entries are infrastructure hops (private ranges)
    and the first public IP encountered walking from the right is the
    client observed by our outermost trusted proxy. Client-supplied values
    sit at the left of the chain, so this traversal ignores them regardless
    of whether they happen to be globally routable.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for hop in reversed(hops):
            if _is_globally_routable(hop):
                return hop
    if request.client and _is_globally_routable(request.client.host):
        return request.client.host
    return None


def current_client_ip() -> str | None:
    """Return the client IP set by ``ClientIPMiddleware`` for the current
    request. Returns ``None`` outside of a request context (e.g. Celery tasks
    or startup code), which callers treat the same as "IP unknown".
    """
    return _CLIENT_IP_CONTEXTVAR.get()


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Stash the per-request client IP into a contextvar so downstream code
    (telemetry, audit logs, rate limiters) can read it without threading the
    request through every call site. One extraction per request.
    """

    async def dispatch(
        self, request: StarletteRequest, call_next: RequestResponseEndpoint
    ) -> Response:
        token = _CLIENT_IP_CONTEXTVAR.set(get_client_ip(request))
        try:
            return await call_next(request)
        finally:
            _CLIENT_IP_CONTEXTVAR.reset(token)
