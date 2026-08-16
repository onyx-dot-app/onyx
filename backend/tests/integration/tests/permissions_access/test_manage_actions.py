"""Integration tests for MANAGE_ACTIONS permission gate.

MANAGE_ACTIONS protects custom-tool + MCP admin endpoints in
``backend/onyx/server/features/tool/api.py`` (admin_router prefix
``/admin/tool``) and ``backend/onyx/server/features/mcp/api.py``
(admin_router prefix ``/admin/mcp``).
"""

import os
from typing import Any
from uuid import uuid4

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey, DATestUser
from tests.integration.tests.permissions._access_matrix import (
    USER_KINDS,
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)

PERMISSION = Permission.MANAGE_ACTIONS.value

_VALIDATE_TOOL_BODY: dict[str, Any] = {
    "definition": {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1.0.0"},
        "paths": {},
    },
}

_OAUTH_CONFIG_BODY: dict[str, Any] = {
    "name": "perm-test-oauth",
    "authorization_url": "https://example.com/authorize",
    "token_url": "https://example.com/token",
    "client_id": "client-id",
    "client_secret": "client-secret",
}

_OAUTH_CONFIG_CREATE_PATH = "/admin/oauth-config/create"

# MANAGE_ACTIONS spans three route clusters — custom tools, OAuth configs and
# MCP servers. Sampled across all of them, and across every method, because a
# GET-only list would miss a mutating route losing its gate.
ENDPOINTS: list[Endpoint] = [
    # custom tools
    ("POST", "/admin/tool/custom", _VALIDATE_TOOL_BODY),
    ("PUT", "/admin/tool/custom/999999", _VALIDATE_TOOL_BODY),
    ("DELETE", "/admin/tool/custom/999999", None),
    ("PATCH", "/admin/tool/status", {"tool_ids": [999999], "enabled": True}),
    ("POST", "/admin/tool/custom/validate", _VALIDATE_TOOL_BODY),
    # OAuth configs
    ("POST", _OAUTH_CONFIG_CREATE_PATH, _OAUTH_CONFIG_BODY),
    ("GET", "/admin/oauth-config/999999", None),
    ("PUT", "/admin/oauth-config/999999", _OAUTH_CONFIG_BODY),
    ("DELETE", "/admin/oauth-config/999999", None),
    # MCP servers
    ("GET", "/admin/mcp/servers", None),
    ("GET", "/admin/mcp/tools", None),
    ("GET", "/admin/mcp/servers/999999", None),
    ("GET", "/admin/mcp/server/999999/tools", None),
    ("GET", "/admin/mcp/server/999999/db-tools", None),
    ("PATCH", "/admin/mcp/server/999999/status", {"is_active": False}),
    ("DELETE", "/admin/mcp/server/999999", None),
]


@pytest.fixture(scope="module")
def holder_user(permission_holder_user_factory: Any) -> DATestUser:
    return permission_holder_user_factory(PERMISSION)


@pytest.fixture(scope="module")
def holder_service_account(
    permission_holder_service_account_factory: Any,
) -> DATestAPIKey:
    return permission_holder_service_account_factory(PERMISSION)


@pytest.mark.parametrize("user_kind,expected", USER_KINDS)
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_access_matrix(
    user_kind: str,
    expected: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures module_reset ran
) -> None:
    creates_oauth_config = path == _OAUTH_CONFIG_CREATE_PATH
    headers, cookies = resolve_credentials(user_kind, request)
    if creates_oauth_config:
        # oauth_config.name is unique-constrained, so a shared name fails for every
        # principal after the first and assert_response reads that as "allowed"
        body = {**_OAUTH_CONFIG_BODY, "name": f"perm-test-oauth-{user_kind}-{uuid4()}"}

    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)

    if creates_oauth_config and resp.status_code == 200:
        call_endpoint(
            "DELETE",
            f"/admin/oauth-config/{resp.json()['id']}",
            None,
            headers,
            cookies,
        )
