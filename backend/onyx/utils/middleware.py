import base64
import hashlib
import re
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from starlette.types import ASGIApp, Receive, Scope, Send

from shared_configs.contextvars import (
    CURRENT_ENDPOINT_CONTEXTVAR,
    CURRENT_TENANT_ID_CONTEXTVAR,
    ONYX_REQUEST_ID_CONTEXTVAR,
)


def tenant_header_middleware(app: ASGIApp) -> ASGIApp:
    async def set_tenant_id(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        onyx_tenant_id = Request(scope).headers.get("X-Onyx-Tenant-ID")
        if not onyx_tenant_id:
            await app(scope, receive, send)
            return

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(onyx_tenant_id)
        try:
            await app(scope, receive, send)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    return set_tenant_id


def request_id_middleware(app: ASGIApp, *, prefix: str) -> ASGIApp:
    async def set_request_id(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        request_id = Request(scope).headers.get("X-Onyx-Request-ID")
        token = ONYX_REQUEST_ID_CONTEXTVAR.set(
            request_id or make_randomized_onyx_request_id(prefix)
        )
        try:
            await app(scope, receive, send)
        finally:
            ONYX_REQUEST_ID_CONTEXTVAR.reset(token)

    return set_request_id


def make_randomized_onyx_request_id(prefix: str) -> str:
    """generates a randomized request id"""

    hash_input = str(uuid.uuid4())
    return _make_onyx_request_id(prefix, hash_input)


def make_structured_onyx_request_id(prefix: str, request_url: str) -> str:
    """Not used yet, but could be in the future!"""
    hash_input = f"{request_url}:{datetime.now(timezone.utc)}"
    return _make_onyx_request_id(prefix, hash_input)


def _make_onyx_request_id(prefix: str, hash_input: str) -> str:
    """helper function to return an id given a string input"""
    hash_obj = hashlib.md5(hash_input.encode("utf-8"), usedforsecurity=False)
    hash_bytes = hash_obj.digest()[:6]  # Truncate to 6 bytes

    # 6 bytes becomes 8 bytes. we shouldn't need to strip but just in case
    # NOTE: possible we'll want more input bytes if id's aren't unique enough
    hash_str = base64.urlsafe_b64encode(hash_bytes).decode("utf-8").rstrip("=")
    onyx_request_id = f"{prefix}:{hash_str}"
    return onyx_request_id


def _build_route_map(app: FastAPI) -> list[tuple[re.Pattern[str], str]]:
    """Build a list of (compiled regex, route template) from the app's routes.

    Used by endpoint context middleware to resolve request paths to route
    templates, avoiding high-cardinality raw paths in metrics labels.
    """
    route_map: list[tuple[re.Pattern[str], str]] = [
        (route.path_regex, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
    ]
    return route_map


def _match_route(route_map: list[tuple[re.Pattern[str], str]], path: str) -> str | None:
    """Match a request path against the route map and return the template."""
    for pattern, template in route_map:
        if pattern.match(path):
            return template
    return None


def add_endpoint_context_middleware(app: FastAPI) -> None:
    """Set CURRENT_ENDPOINT_CONTEXTVAR so Prometheus pool metrics can
    attribute DB connections to the endpoint that checked them out.

    Used by ``onyx_db_connections_held_by_endpoint`` and
    ``onyx_db_connection_hold_seconds`` in the pool event listeners.

    Resolves request paths to route templates (e.g. /api/chat/{chat_id}
    instead of /api/chat/abc-123) to keep metric label cardinality low.

    Must be registered AFTER all routes are added to the app.
    """
    route_map = _build_route_map(app)

    def endpoint_context_middleware(app: ASGIApp) -> ASGIApp:
        async def set_endpoint_context(
            scope: Scope, receive: Receive, send: Send
        ) -> None:
            if scope["type"] != "http":
                await app(scope, receive, send)
                return

            handler = _match_route(route_map, Request(scope).url.path)
            token = CURRENT_ENDPOINT_CONTEXTVAR.set(handler or "unmatched")
            try:
                await app(scope, receive, send)
            finally:
                CURRENT_ENDPOINT_CONTEXTVAR.reset(token)

        return set_endpoint_context

    app.add_middleware(endpoint_context_middleware)
