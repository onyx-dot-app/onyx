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

from typing import Any

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL

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
) -> requests.Response:
    kwargs: dict[str, Any] = {"headers": headers or {}, "timeout": 30}
    if cookies is not None:
        kwargs["cookies"] = cookies
    if body is not None:
        kwargs["json"] = body
    return requests.request(method, f"{API_SERVER_URL}{path}", **kwargs)


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


def _is_gate_denial(resp: requests.Response) -> bool:
    """True iff the 403 came from an auth-layer gate, not the handler.

    Two auth-layer shapes exist:

    1. ``require_permission`` → ``OnyxError(INSUFFICIENT_PERMISSIONS)``
       serialised as ``{"error_code": "INSUFFICIENT_PERMISSIONS", ...}``.
    2. ``current_user`` rejects a user whose effective_permissions list is
       empty via ``BasicAuthenticationError`` → plain
       ``{"detail": "Access denied. User has limited permissions."}``.

    A handler-level 403 (e.g. persona handlers re-raising ``ValueError`` as
    ``HTTPException(403)``) matches neither shape.
    """
    if resp.status_code != 403:
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    if body.get("error_code") == "INSUFFICIENT_PERMISSIONS":
        return True
    if body.get("detail") == _LIMITED_USER_DETAIL:
        return True
    return False


def assert_response(
    resp: requests.Response,
    method: str,
    path: str,
    user_kind: str,
    expected: str,
) -> None:
    if expected == "allowed":
        # A caller who cleared the gate may still hit a handler-level 403
        # (e.g. persona-not-found paths that reuse 403). We only care that
        # the permission gate itself did not reject the request.
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
    elif expected == "anon_denied":
        assert resp.status_code in (401, 403), (
            f"Anonymous should be denied on {method} {path}, " f"got {resp.status_code}"
        )
    else:
        raise ValueError(f"Unknown expected value: {expected}")
