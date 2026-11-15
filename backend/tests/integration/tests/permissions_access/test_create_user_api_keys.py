"""Integration tests for CREATE_USER_API_KEYS permission gate.

Covers the personal-access-token creation endpoint in
``backend/onyx/server/pat/api.py`` (router prefix ``/user/pats``).
The basic-access GET endpoints on the same router are covered by
``test_basic_access.py`` — this file only exercises the CREATE token.

The seeded Basic group grants this permission, so every standard user is a
holder. The matrix below replaces the shared USER_KINDS to expect that.
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey, DATestUser
from tests.integration.tests.permissions._access_matrix import (
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)

PERMISSION = Permission.CREATE_USER_API_KEYS.value

USER_KINDS: list[tuple[str, str]] = [
    ("admin", "allowed"),
    ("holder", "allowed"),
    ("service_account_holder", "allowed"),
    ("basic", "allowed"),
    ("service_account", "denied"),
    ("bot", "denied"),
    ("ext_perm", "denied"),
    ("anonymous", "anon_denied"),
]

_CREATE_PAT_BODY: dict[str, Any] = {
    "name": "perm-test-pat",
    "expiration_days": 7,
}

ENDPOINTS: list[Endpoint] = [
    ("POST", "/user/pats", _CREATE_PAT_BODY),
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
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)
