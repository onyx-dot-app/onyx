"""The microVM router is mounted only with `SANDBOX_RUNTIME=firecracker|auto`
on Kubernetes (`SANDBOX_FIRECRACKER_ENABLED`); the admin sandbox status on
every runtime."""

import importlib

import pytest
from fastapi.routing import APIRoute

from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.microvm.api import (
    SANDBOX_NODE_DEREGISTER_PATH,
    SANDBOX_NODE_SIGNING_KEY_PATH,
    SANDBOX_NODE_STATE_REPORT_PATH,
)


def _has_signing_key_route(runtime: SandboxRuntime) -> bool:
    onyx_main = importlib.import_module("onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(onyx_main, "SANDBOX_FIRECRACKER_ENABLED", runtime.uses_firecracker)
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


def test_node_routes_follow_the_runtime() -> None:
    assert _has_signing_key_route(SandboxRuntime.AUTO)
    assert _has_post_route(SandboxRuntime.AUTO, SANDBOX_NODE_STATE_REPORT_PATH)
    assert not _has_signing_key_route(SandboxRuntime.OFF)


def test_admin_status_route_on_every_runtime() -> None:
    for runtime in SandboxRuntime:
        assert _has_get_route(runtime, "/admin/sandbox/status")


def _has_route(runtime: SandboxRuntime, path: str, method: str) -> bool:
    onyx_main = importlib.import_module("onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(onyx_main, "SANDBOX_FIRECRACKER_ENABLED", runtime.uses_firecracker)
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        app = onyx_main.get_application()
    return any(
        isinstance(route, APIRoute) and route.path == path and method in route.methods
        for route in app.routes
    )


def _has_post_route(runtime: SandboxRuntime, path: str) -> bool:
    return _has_route(runtime, path, "POST")


def _has_get_route(runtime: SandboxRuntime, path: str) -> bool:
    return _has_route(runtime, path, "GET")


def test_state_report_route_only_with_firecracker_runtime() -> None:
    assert SANDBOX_NODE_STATE_REPORT_PATH == "/microvm/node/state"
    assert not _has_post_route(SandboxRuntime.POD, SANDBOX_NODE_STATE_REPORT_PATH)
    assert _has_post_route(SandboxRuntime.FIRECRACKER, SANDBOX_NODE_STATE_REPORT_PATH)


def test_deregister_route_only_with_firecracker_runtime() -> None:
    assert SANDBOX_NODE_DEREGISTER_PATH == "/microvm/node/deregister"
    assert not _has_post_route(SandboxRuntime.POD, SANDBOX_NODE_DEREGISTER_PATH)
    assert _has_post_route(SandboxRuntime.FIRECRACKER, SANDBOX_NODE_DEREGISTER_PATH)


def test_auto_on_docker_mounts_no_node_routes() -> None:
    """`auto` with SANDBOX_BACKEND=docker turns Firecracker off."""
    onyx_main = importlib.import_module("onyx.main")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(onyx_main, "SANDBOX_FIRECRACKER_ENABLED", False)
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        app = onyx_main.get_application()
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert SANDBOX_NODE_STATE_REPORT_PATH not in paths
    assert "/admin/sandbox/status" in paths
