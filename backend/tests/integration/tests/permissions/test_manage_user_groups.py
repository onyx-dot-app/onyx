"""Integration tests for MANAGE_USER_GROUPS permission gate (Enterprise).

MANAGE_USER_GROUPS protects the user-group admin endpoints in
``backend/ee/onyx/server/user_group/api.py`` (router prefix ``/manage``).

Note: ``GET /manage/admin/user-group`` is guarded by READ_USER_GROUPS
(implied by MANAGE_USER_GROUPS) so we deliberately exclude it here —
this file only covers endpoints that require the MANAGE token directly.
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.permissions._access_matrix import assert_response
from tests.integration.tests.permissions._access_matrix import call_endpoint
from tests.integration.tests.permissions._access_matrix import Endpoint
from tests.integration.tests.permissions._access_matrix import resolve_credentials
from tests.integration.tests.permissions._access_matrix import USER_KINDS

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User-group permission tests are enterprise only",
)

PERMISSION = Permission.MANAGE_USER_GROUPS.value

_CREATE_GROUP_BODY: dict[str, Any] = {
    "name": "perm-test-user-group",
    "user_ids": [],
    "cc_pair_ids": [],
}

ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/admin/user-group/999999/permissions", None),
    ("POST", "/manage/admin/user-group", _CREATE_GROUP_BODY),
    ("DELETE", "/manage/admin/user-group/999999", None),
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
