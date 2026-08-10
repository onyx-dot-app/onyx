"""Integration tests for MANAGE_CONNECTORS permission gate.

Complements ``test_file_connector_permissions.py`` (which exercises the
file-connector flow in depth) by asserting the breadth of general
connector management endpoints in
``backend/onyx/server/documents/connector.py`` (router prefix ``/manage``).
"""

import os
from typing import Any

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

PERMISSION = Permission.MANAGE_CONNECTORS.value

ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/admin/connector", None),
    ("GET", "/manage/admin/connector/failed-indexing-status", None),
    ("POST", "/manage/admin/connector/run-once", {"connector_id": 999999}),
    ("DELETE", "/manage/admin/connector/999999", None),
]

# Gated on READ_CONNECTORS, which MANAGE_CONNECTORS implies. Kept here because
# the holder must reach them, but listed apart so the matrix doesn't mislabel them.
IMPLIED_READ_ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/admin/connector/status", None),
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


@pytest.mark.parametrize("user_kind,expected", USER_KINDS)
@pytest.mark.parametrize("method,path,body", IMPLIED_READ_ENDPOINTS)
def test_implied_read_access_matrix(
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
