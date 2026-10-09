"""Shared helpers for per-permission access-matrix tests.

Each custom-permission test file exercises the same 7-user matrix:

  admin          → allowed (FULL_ADMIN_PANEL_ACCESS bypass)
  holder         → allowed (group grants only the permission under test)
  basic          → denied
  service_account→ denied
  bot            → denied
  ext_perm       → denied
  anonymous      → denied (401 or 403)

"Allowed" is interpreted permissively: any response code that is *not*
401/403 means the permission gate was reached. We don't require 2xx
because several gated endpoints need path parameters pointing at real
resources (e.g. ``PATCH /admin/persona/{id}/listed``) and returning 404
on a bogus ID is fine — we only care that the caller was not blocked by
the gate.
"""

from collections.abc import Callable
from enum import Enum
from typing import Any, NamedTuple

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client

# (method, path, json body or None)
Endpoint = tuple[str, str, dict[str, Any] | None]


# User-kind + expected-outcome pairs parametrized into every test file.
# Each test file's local ``holder_user`` fixture supplies the "holder" kind.
USER_KINDS: list[tuple[str, str]] = [
    ("admin", "allowed"),
    ("holder", "allowed"),
    ("service_account_holder", "allowed"),
    ("basic", "denied"),
    ("service_account", "denied"),
    ("bot", "denied"),
    ("ext_perm", "denied"),
    ("anonymous", "anon_denied"),
]


def call_endpoint(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    headers: dict[str, str] | None,
    cookies: Any = None,
) -> httpx.Response:
    # Go through the shared client, not `requests` — it resolves to the in-process
    # TestClient locally and a real httpx.Client in the docker e2e. Raw requests only
    # ever reaches a live server on :8080, so it can't run in-process.
    kwargs: dict[str, Any] = {"headers": headers or {}, "timeout": 30}
    if cookies is not None:
        kwargs["cookies"] = cookies
    if body is not None:
        kwargs["json"] = body
    return client.request(method, f"{API_SERVER_URL}{path}", **kwargs)


def resolve_credentials(
    user_kind: str, request: pytest.FixtureRequest
) -> tuple[dict[str, str], Any]:
    """Map a user-kind string to (headers, cookies) by pulling the matching
    shared fixture from ``conftest.py``. Per-file ``holder_user`` /
    ``holder_service_account`` fixtures are looked up by well-known names."""
    if user_kind == "anonymous":
        return {}, None
    if user_kind == "service_account":
        sa = request.getfixturevalue("limited_service_account")
        return sa.headers, None
    if user_kind == "service_account_holder":
        sa = request.getfixturevalue("holder_service_account")
        return sa.headers, None
    if user_kind == "bot":
        return request.getfixturevalue("bot_user_headers"), None
    if user_kind == "ext_perm":
        return request.getfixturevalue("ext_perm_user_headers"), None

    fixture_map = {
        "admin": "permission_admin_user",
        "basic": "permission_basic_user",
        "holder": "holder_user",
    }
    user = request.getfixturevalue(fixture_map[user_kind])
    return user.headers, user.cookies


_LIMITED_USER_DETAIL = "Access denied. User has limited permissions."


class Gate(str, Enum):
    """Which auth layer produced a 403. All four denial sites share
    ``INSUFFICIENT_PERMISSIONS`` — the only 403 code — so only the detail message
    tells them apart, and a manager denied at GATE 1 vs GATE 2 means opposite
    things (route forgot allow_scope vs scope check working)."""

    GATE_1 = "gate_1"  # require_permission
    GATE_2 = "gate_2"  # assert_within_scope / assert_manages_group
    ADMIN_ONLY = "admin_only"  # assert_global, or a handler doing the same test inline
    LIMITED_USER = "limited_user"  # current_user, empty effective_permissions
    NOT_A_GATE = "not_a_gate"  # handler-level 403, or not a 403 at all


# Prefixes, not equality, so rewording a message can't silently reclassify the layer.
_GATE_BY_DETAIL_PREFIX: list[tuple[str, Gate]] = [
    ("You do not have the required permissions", Gate.GATE_1),
    ("Group managers can only act", Gate.GATE_2),
    ("This action is restricted to administrators", Gate.ADMIN_ONLY),
    # delete_document_set can't call assert_global — it exempts a groupless set's
    # creator — so it tests PermissionAuthority.GLOBAL inline and needs its own entry.
    ("Deleting a shared document set is restricted to administrators", Gate.ADMIN_ONLY),
    (_LIMITED_USER_DETAIL, Gate.LIMITED_USER),
    # Handler-level checks reusing INSUFFICIENT_PERMISSIONS — listed so the fallback
    # below doesn't file them as GATE 1. The caller cleared every gate.
    ("You can only delete agents you created", Gate.NOT_A_GATE),
    ("Query history has been disabled", Gate.NOT_A_GATE),
]


def gate_of(resp: httpx.Response) -> Gate:
    """Classify a 403 by the auth layer that raised it. A handler-level 403 (e.g.
    persona handlers re-raising ValueError) matches nothing and is NOT_A_GATE."""
    if resp.status_code != 403:
        return Gate.NOT_A_GATE
    try:
        body = resp.json()
    except ValueError:
        return Gate.NOT_A_GATE
    if not isinstance(body, dict):
        return Gate.NOT_A_GATE
    detail = body.get("detail")
    if isinstance(detail, str):
        for prefix, gate in _GATE_BY_DETAIL_PREFIX:
            if detail.startswith(prefix):
                return gate
    # Unrecognised detail is still an auth denial; fall back rather than lose it.
    if body.get("error_code") == "INSUFFICIENT_PERMISSIONS":
        return Gate.GATE_1
    return Gate.NOT_A_GATE


def _is_gate_denial(resp: httpx.Response) -> bool:
    return gate_of(resp) is not Gate.NOT_A_GATE


_EXPECTED_GATE: dict[str, Gate] = {
    "denied_gate1": Gate.GATE_1,
    "denied_gate2": Gate.GATE_2,
    "denied_admin_only": Gate.ADMIN_ONLY,
}


def assert_response(
    resp: httpx.Response,
    method: str,
    path: str,
    user_kind: str,
    expected: str,
) -> None:
    """``expected``: allowed | denied (any auth layer) | denied_gate1 |
    denied_gate2 | denied_admin_only | anon_denied (401 or 403)."""
    if expected == "allowed":
        # Tolerates a handler-level 403 (bogus ids reuse 403); only the gate matters.
        assert resp.status_code != 401 and not _is_gate_denial(resp), (
            f"{user_kind} should not be blocked by permission gate on "
            f"{method} {path}, got {resp.status_code} "
            f"(body={resp.text[:200]})"
        )
    elif expected == "denied":
        assert resp.status_code == 403 and _is_gate_denial(resp), (
            f"{user_kind} should be denied by permission gate on "
            f"{method} {path}, got {resp.status_code} "
            f"(body={resp.text[:200]})"
        )
    elif expected in _EXPECTED_GATE:
        wanted = _EXPECTED_GATE[expected]
        actual = gate_of(resp)
        assert actual is wanted, (
            f"{user_kind} should be denied by {wanted.value} on {method} {path}, "
            f"but got {actual.value} (status={resp.status_code}, "
            f"body={resp.text[:200]})"
        )
    elif expected == "anon_denied":
        assert resp.status_code in (401, 403), (
            f"Anonymous should be denied on {method} {path}, got {resp.status_code}"
        )
    else:
        raise ValueError(f"Unknown expected value: {expected}")


# Scope vocabulary, for the permissions in SCOPED_MANAGER_PERMISSIONS. Separate
# from USER_KINDS because scope asks "may this principal act on THIS resource",
# which needs a resource and a managed/unmanaged group pair.

# (kind, expectation in the managed group, expectation outside it). A manager
# clears GATE 1 either way — a GATE 1 denial would mean the route forgot
# allow_scope — and is stopped by GATE 2 only out of scope.
SCOPE_USER_KINDS: list[tuple[str, str, str]] = [
    ("admin", "allowed", "allowed"),
    ("holder", "allowed", "allowed"),
    ("manager", "allowed", "denied_gate2"),
    ("plain_member", "denied_gate1", "denied_gate1"),
]


class ScopeEndpoint(NamedTuple):
    """A route under scope test. ``path``/``body`` are built per resource, because
    scope is only observable against a concrete resource."""

    method: str
    path: Callable[[Any], str]
    body: Callable[[Any], dict[str, Any] | None] = lambda _resource: None
    label: str = ""


def resolve_scope_credentials(
    user_kind: str, request: pytest.FixtureRequest
) -> tuple[dict[str, str], Any]:
    """``holder`` reuses the calling module's own fixture, so a file's scope block
    and access-matrix block agree on what holding this permission means."""
    fixture_map = {
        "admin": "permission_admin_user",
        "holder": "holder_user",
        "manager": "scoped_manager_user",
        "plain_member": "scoped_group_member",
    }
    user = request.getfixturevalue(fixture_map[user_kind])
    return user.headers, user.cookies


def assert_scope_case(
    endpoint: ScopeEndpoint,
    resource_id: Any,
    user_kind: str,
    expected: str,
    request: pytest.FixtureRequest,
) -> None:
    headers, cookies = resolve_scope_credentials(user_kind, request)
    path = endpoint.path(resource_id)
    resp = call_endpoint(
        endpoint.method, path, endpoint.body(resource_id), headers, cookies
    )
    assert_response(resp, endpoint.method, path, user_kind, expected)
