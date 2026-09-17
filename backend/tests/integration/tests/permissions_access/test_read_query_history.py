"""Integration tests for READ_QUERY_HISTORY permission gate (Enterprise).

Covers the query-history admin endpoints in
``backend/ee/onyx/server/query_history/api.py`` (router has no prefix).

``chat-session*`` backs the table and its detail drawer, ``query-history/*`` the
CSV export. Bogus ids are fine — the gate runs first.
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
    reason="Query-history endpoints are enterprise only",
)

PERMISSION = Permission.READ_QUERY_HISTORY.value

_BOGUS_UUID = "00000000-0000-0000-0000-000000000000"

ENDPOINTS: list[Endpoint] = [
    # Chat sessions — what the table and its detail drawer read
    ("GET", f"/admin/chat-sessions?user_id={_BOGUS_UUID}", None),
    ("GET", "/admin/chat-session-history", None),
    ("GET", f"/admin/chat-session-history/{_BOGUS_UUID}", None),
    # CSV export
    ("GET", "/admin/query-history/list", None),
    ("POST", "/admin/query-history/start-export", None),
    ("GET", "/admin/query-history/export-status?request_id=nonexistent", None),
    ("GET", "/admin/query-history/download?request_id=nonexistent", None),
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
