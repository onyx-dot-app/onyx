"""Tests for the impersonation feature gate.

Impersonation is gated at the router level: the endpoint is only registered when
IMPERSONATION_ENABLED is set. When disabled it is not mounted at all, so a
request 404s rather than reaching the handler or the auth layer.
"""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from ee.onyx.server.tenants import api
from ee.onyx.server.tenants.api import build_tenants_router

IMPERSONATE_PATH = "/tenants/impersonate"


def _paths(router: APIRouter) -> set[str]:
    return {route.path for route in router.routes if isinstance(route, APIRoute)}


def test_impersonate_not_registered_when_disabled() -> None:
    router = build_tenants_router(impersonation_enabled=False)
    assert IMPERSONATE_PATH not in _paths(router)


def test_impersonate_registered_when_enabled() -> None:
    router = build_tenants_router(impersonation_enabled=True)
    assert IMPERSONATE_PATH in _paths(router)


def test_disabled_by_default() -> None:
    # The module-level router is built from the real env, which leaves the flag
    # off by default — guards against the route being wired in unconditionally.
    assert IMPERSONATE_PATH not in _paths(api.router)
