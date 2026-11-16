"""The playground has no Stripe, so the billing and proxy routes are not mounted
there. The routes the control plane calls stay. Cloud keeps everything."""

import importlib
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from ee.onyx.server.tenants import api
from ee.onyx.server.tenants.api import build_tenants_router

CONTROL_PLANE_PATHS = {
    "/tenants/product-gating",
    "/tenants/product-gating/full-sync",
    "/tenants/tier-update",
}
BILLING_PATHS = {
    "/tenants/billing-information",
    "/tenants/seats/update",
    "/tenants/create-customer-portal-session",
    "/tenants/create-checkout-session",
    "/tenants/create-subscription-session",
    "/tenants/stripe-publishable-key",
}


def _paths(router: APIRouter) -> set[str]:
    return {route.path for route in router.routes if isinstance(route, APIRoute)}


def test_playground_mounts_no_billing_or_proxy_routes() -> None:
    paths = _paths(build_tenants_router(playground=True))

    assert CONTROL_PLANE_PATHS <= paths
    assert not BILLING_PATHS & paths
    assert not {path for path in paths if path.startswith("/proxy/")}


def test_cloud_mounts_everything() -> None:
    paths = _paths(build_tenants_router(playground=False))

    assert CONTROL_PLANE_PATHS | BILLING_PATHS <= paths
    assert {path for path in paths if path.startswith("/proxy/")}


def test_cloud_by_default() -> None:
    # The module-level router is built from the real env, where the flag is off.
    assert BILLING_PATHS <= _paths(api.router)


def _app_paths(playground: bool) -> set[str]:
    # onyx.main must load before ee.onyx.main, or the import is circular.
    onyx_main = importlib.import_module("onyx.main")
    ee_main = importlib.import_module("ee.onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ee_main, "IS_PLAYGROUND", playground)
        mp.setattr(ee_main, "MULTI_TENANT", True)
        mp.setattr(onyx_main, "OAUTH_PROVIDER_SETTINGS", MagicMock())
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        app: FastAPI = ee_main.get_application()
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_admin_billing_not_mounted_on_the_playground() -> None:
    paths = _app_paths(playground=True)

    assert not {path for path in paths if path.startswith("/admin/billing/")}
    assert CONTROL_PLANE_PATHS <= paths


def test_admin_billing_mounted_on_cloud() -> None:
    assert "/admin/billing/billing-information" in _app_paths(playground=False)
