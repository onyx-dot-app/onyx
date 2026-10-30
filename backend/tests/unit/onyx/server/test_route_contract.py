"""Contract tests over every FastAPI route.

1. ``route_contract_manifest.json`` pins each route's auth gate, so any change
   to a route's permission shows up in review. Regenerate it with
   ``ONYX_UPDATE_ROUTE_MANIFEST=1 pytest <this file>``.
2. A handler that admits scoped group managers (``allow_scope=True``) must reach
   a registered GATE-2 helper.
3. A GET/HEAD handler must not commit or call a ``__no_commit`` writer.

Checks 2 and 3 walk the handler source and the onyx/ee functions it calls.
``route_contract_baseline.json`` lists the existing violations. It can only
shrink: a new violation fails, and an entry that no longer violates fails too.
"""

import ast
import importlib
import inspect
import json
import os
import textwrap
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_global
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.mcp import update_mcp_server__no_commit
from onyx.db.models import User

_HERE = Path(__file__).parent
MANIFEST_PATH = _HERE / "route_contract_manifest.json"
BASELINE_PATH = _HERE / "route_contract_baseline.json"
SCOPE_SECTION = "allow_scope_without_gate2"
GET_WRITE_SECTION = "get_handler_writes"

# Functions that apply a scoped manager's object-level limit (GATE 2).
GATE2_HELPERS: frozenset[str] = frozenset(
    {
        "onyx.auth.scoped_permissions:within_scope",
        "onyx.auth.scoped_permissions:assert_within_scope",
        "onyx.auth.scoped_permissions:manages_group",
        "onyx.auth.scoped_permissions:assert_manages_group",
        "onyx.auth.scoped_permissions:assert_global",
        "onyx.auth.scoped_permissions:get_scoped_groups",
        "onyx.auth.scoped_permissions:get_visible_user_group_ids",
        "onyx.auth.scoped_permissions:scope_data_access_group_ids",
        "onyx.db.scoped_permissions:scoped_group_ids_subquery",
        "onyx.db.scoped_permissions:fetch_managed_group_ids",
        "onyx.db.scoped_permissions:within_managed_scope_clause",
        "onyx.db.connector_credential_pair:verify_user_has_access_to_cc_pair",
        "onyx.db.connector_credential_pair:verify_user_can_manage_all_cc_pairs",
        "onyx.db.connector_credential_pair:verify_user_can_edit_connector",
        "onyx.db.connector_credential_pair:get_managed_cc_pair_ids",
        "onyx.db.connector_credential_pair:_manage_access_clause",
        "onyx.db.credentials:fetch_editable_credential_ids",
        "onyx.db.persona:can_edit_persona",
        "onyx.db.persona:persona_edit_within_scope",
        "onyx.db.tools:can_manage_mcp_server",
        "onyx.db.tools:can_manage_tool",
        "onyx.db.tools:can_manage_own_tool",
        "onyx.server.features.mcp.api:_ensure_mcp_server_owner_or_admin",
        "onyx.server.features.mcp.api:_ensure_mcp_server_viewable",
        "onyx.server.features.oauth_config.api:_assert_can_manage_oauth_config",
    }
)

# Call depth below the handler that the source walk follows.
WALK_DEPTH = 3
_FOLLOWED_PACKAGES = ("onyx.", "ee.onyx.")


# --- route discovery --------------------------------------------------------


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    endpoint: Callable[..., Any]
    dependency_calls: tuple[Callable[..., Any], ...]

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


# Non-permission auth dependencies, labelled by name in the manifest.
_AUTH_DEPENDENCY_NAMES: frozenset[str] = frozenset(
    {
        "bind_craft_session",
        "control_plane_dep",
        "current_chat_accessible_user",
        "current_cloud_superuser",
        "current_limited_user",
        "current_user",
        "current_user_dependency",
        "current_user_from_websocket",
        "current_user_from_websocket_cookie",
        "current_user_with_expired_token",
        "get_license_payload",
        "get_license_payload_allow_expired",
        "get_optional_license_payload",
        "optional_user",
        "scope_exempt",
        "verify_metrics_token",
        "verify_scim_token",
    }
)


def _attr(fn: object, name: str) -> Any:
    return getattr(fn, name, None)  # ods: ignore[getattr]


def _is_auth_dependency(call: object) -> bool:
    return bool(_attr(call, "_is_require_permission")) or (
        _attr(call, "__name__") in _AUTH_DEPENDENCY_NAMES
    )


def _flatten(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    """Every dependency call, without descending into an auth dependency."""
    for dependency in dependant.dependencies:
        if dependency.call is None:
            continue
        yield dependency.call
        if not _is_auth_dependency(dependency.call):
            yield from _flatten(dependency)


def iter_routes(app: FastAPI) -> Iterator[RouteInfo]:
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods = sorted(route.methods or ())
        elif isinstance(route, APIWebSocketRoute):
            methods = ["WS"]
        else:
            continue
        calls = tuple(_flatten(route.dependant))
        for method in methods:
            yield RouteInfo(method, route.path, route.endpoint, calls)


def _permission_dependencies(route: RouteInfo) -> list[Callable[..., Any]]:
    return [c for c in route.dependency_calls if _attr(c, "_is_require_permission")]


def _gate_label(route: RouteInfo) -> str:
    labels: set[str] = set()
    for call in route.dependency_calls:
        if _attr(call, "_is_require_permission"):
            permission: Permission = _attr(call, "_required_permission")
            label = permission.value
            if _attr(call, "_allow_scope"):
                label += " +scope"
            if _attr(call, "_allow_anonymous"):
                label += " +anonymous"
            labels.add(label)
        elif _is_auth_dependency(call):
            labels.add(_attr(call, "__name__"))
    return ", ".join(sorted(labels)) or "none"


def build_manifest(app: FastAPI) -> dict[str, str]:
    manifest: dict[str, set[str]] = {}
    for route in iter_routes(app):
        manifest.setdefault(route.key, set()).add(_gate_label(route))
    return {key: " | ".join(sorted(labels)) for key, labels in manifest.items()}


# --- source walk ------------------------------------------------------------


def _function_body(fn: Callable[..., Any]) -> list[ast.stmt]:
    try:
        source = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return []
    tree = ast.parse(source)
    node = tree.body[0]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Skip parameter defaults: Depends(...) there is not a handler call.
        return node.body
    return []


@dataclass
class CallGraph:
    """What a handler reaches within ``WALK_DEPTH`` calls."""

    functions: set[str]
    call_names: set[str]


def _qualified(fn: types.FunctionType) -> str:
    return f"{fn.__module__}:{fn.__qualname__}"


def _resolve(node: ast.expr, namespace: dict[str, Any]) -> object:
    if isinstance(node, ast.Name):
        return namespace.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = namespace.get(node.value.id)
        if isinstance(owner, types.ModuleType):
            return _attr(owner, node.attr)
    return None


def walk_calls(handler: Callable[..., Any], depth: int = WALK_DEPTH) -> CallGraph:
    graph = CallGraph(functions=set(), call_names=set())
    seen: set[int] = set()
    frontier: list[Callable[..., Any]] = [inspect.unwrap(handler)]
    for _ in range(depth + 1):
        next_frontier: list[Callable[..., Any]] = []
        for fn in frontier:
            namespace: dict[str, Any] = dict(_attr(fn, "__globals__") or {})
            for stmt in _function_body(fn):
                for node in ast.walk(stmt):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    if isinstance(func, ast.Name):
                        graph.call_names.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        graph.call_names.add(func.attr)
                    target = _resolve(func, namespace)
                    if not callable(target):
                        continue
                    target = inspect.unwrap(target)
                    if not isinstance(target, types.FunctionType):
                        continue
                    graph.functions.add(_qualified(target))
                    module = target.__module__ or ""
                    if id(target) not in seen and module.startswith(_FOLLOWED_PACKAGES):
                        seen.add(id(target))
                        next_frontier.append(target)
        frontier = next_frontier
    return graph


def scope_violations(app: FastAPI) -> set[str]:
    violations: set[str] = set()
    for route in iter_routes(app):
        if not any(_attr(c, "_allow_scope") for c in _permission_dependencies(route)):
            continue
        if not walk_calls(route.endpoint).functions & GATE2_HELPERS:
            violations.add(route.key)
    return violations


def get_write_violations(app: FastAPI) -> set[str]:
    violations: set[str] = set()
    for route in iter_routes(app):
        if route.method not in ("GET", "HEAD"):
            continue
        names = walk_calls(route.endpoint).call_names
        if "commit" in names or any(n.endswith("__no_commit") for n in names):
            violations.add(route.key)
    return violations


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> Iterator[FastAPI]:
    # onyx.main must load before ee.onyx.main, or the import is circular.
    onyx_main = importlib.import_module("onyx.main")
    ee_main = importlib.import_module("ee.onyx.main")

    # Pin the flags that add or remove routers so the route set is stable.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ee_main, "MULTI_TENANT", True)
        mp.setattr(onyx_main, "OAUTH_ENABLED", True)
        mp.setattr(onyx_main, "OAUTH_CLIENT_ID", "route-contract-client")
        mp.setattr(onyx_main, "OAUTH_CLIENT_SECRET", "route-contract-value")
        mp.setattr(onyx_main, "OAUTH_PROVIDER_SETTINGS", MagicMock())
        mp.setattr(onyx_main, "ENABLE_PUBLIC_DOCS", False)
        mp.setattr(onyx_main, "APP_API_PREFIX", "")
        yield ee_main.get_application()


def _load_baseline() -> dict[str, dict[str, str]]:
    return json.loads(BASELINE_PATH.read_text())


def _assert_matches_baseline(found: set[str], section: str, what: str) -> None:
    allowed = set(_load_baseline()[section])
    new = sorted(found - allowed)
    stale = sorted(allowed - found)
    assert not new, (
        f"{what}: {new}. Fix the handler. Do not add it to "
        f"{BASELINE_PATH.name}[{section!r}]."
    )
    assert not stale, (
        f"Fixed, so remove from {BASELINE_PATH.name}[{section!r}]: {stale}"
    )


# --- contract tests ---------------------------------------------------------


def test_route_permission_manifest_is_current(app: FastAPI) -> None:
    current = build_manifest(app)
    if os.environ.get("ONYX_UPDATE_ROUTE_MANIFEST"):
        MANIFEST_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    committed: dict[str, str] = json.loads(MANIFEST_PATH.read_text())
    changed = {
        key: (committed.get(key), current.get(key))
        for key in committed.keys() | current.keys()
        if committed.get(key) != current.get(key)
    }
    assert not changed, (
        "Route gates changed (committed, current). Review them, then run "
        f"ONYX_UPDATE_ROUTE_MANIFEST=1 pytest {Path(__file__).name}: {changed}"
    )


def test_gate2_helpers_exist() -> None:
    for spec in GATE2_HELPERS:
        module_name, name = spec.split(":")
        fn = _attr(importlib.import_module(module_name), name)
        assert callable(fn) and _qualified(fn) == spec, spec


def test_allow_scope_handlers_reach_a_gate2_helper(app: FastAPI) -> None:
    _assert_matches_baseline(
        scope_violations(app),
        SCOPE_SECTION,
        "allow_scope=True handlers that reach no GATE-2 helper",
    )


def test_get_handlers_do_not_write(app: FastAPI) -> None:
    _assert_matches_baseline(
        get_write_violations(app),
        GET_WRITE_SECTION,
        "GET/HEAD handlers that commit or call a __no_commit writer",
    )


# --- the checks catch a violating route --------------------------------------


def _dummy_app() -> FastAPI:
    router = APIRouter()

    @router.get("/scoped-read-no-gate")
    def scoped_read_no_gate(
        _user: User = Depends(
            require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
        ),
    ) -> None:
        return None

    @router.get("/scoped-read-gated")
    def scoped_read_gated(
        user: User = Depends(
            require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
        ),
    ) -> None:
        assert_global(user, permission=Permission.MANAGE_CONNECTORS)

    @router.get("/read-that-commits")
    def read_that_commits(
        _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
        db_session: Session = Depends(get_session),
    ) -> None:
        db_session.commit()

    @router.get("/read-that-calls-a-writer")
    def read_that_calls_a_writer(
        _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
        db_session: Session = Depends(get_session),
    ) -> None:
        update_mcp_server__no_commit(server_id=1, db_session=db_session)

    app = FastAPI()
    app.include_router(router)
    return app


def test_checks_flag_a_violating_route() -> None:
    dummy = _dummy_app()
    assert scope_violations(dummy) == {"GET /scoped-read-no-gate"}
    assert get_write_violations(dummy) == {
        "GET /read-that-commits",
        "GET /read-that-calls-a-writer",
    }
    assert build_manifest(dummy) == {
        "GET /scoped-read-no-gate": "manage:connectors +scope",
        "GET /scoped-read-gated": "manage:connectors +scope",
        "GET /read-that-commits": "basic",
        "GET /read-that-calls-a-writer": "basic",
    }
