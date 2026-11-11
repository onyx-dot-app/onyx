"""The microVM router is mounted only with `SANDBOX_RUNTIME=firecracker`."""

import importlib

import pytest
from fastapi.routing import APIRoute

from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.microvm.api import (
    SANDBOX_NODE_SIGNING_KEY_PATH,
    SANDBOX_NODE_STATE_REPORT_PATH,
)


def _has_signing_key_route(runtime: SandboxRuntime) -> bool:
    onyx_main = importlib.import_module("onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(onyx_main, "SANDBOX_RUNTIME", runtime)
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        app = onyx_main.get_application()
    return any(
        isinstance(route, APIRoute)
        and route.path == SANDBOX_NODE_SIGNING_KEY_PATH
        and "PUT" in route.methods
        for route in app.routes
    )


def test_signing_key_route_path() -> None:
    assert SANDBOX_NODE_SIGNING_KEY_PATH == "/microvm/node/signing-key"


def test_signing_key_route_absent_with_pod_runtime() -> None:
    assert not _has_signing_key_route(SandboxRuntime.POD)


def test_signing_key_route_present_with_firecracker_runtime() -> None:
    assert _has_signing_key_route(SandboxRuntime.FIRECRACKER)


def _has_state_report_route(runtime: SandboxRuntime) -> bool:
    onyx_main = importlib.import_module("onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(onyx_main, "SANDBOX_RUNTIME", runtime)
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        app = onyx_main.get_application()
    return any(
        isinstance(route, APIRoute)
        and route.path == SANDBOX_NODE_STATE_REPORT_PATH
        and "POST" in route.methods
        for route in app.routes
    )


def test_state_report_route_only_with_firecracker_runtime() -> None:
    assert SANDBOX_NODE_STATE_REPORT_PATH == "/microvm/node/state"
    assert not _has_state_report_route(SandboxRuntime.POD)
    assert _has_state_report_route(SandboxRuntime.FIRECRACKER)
