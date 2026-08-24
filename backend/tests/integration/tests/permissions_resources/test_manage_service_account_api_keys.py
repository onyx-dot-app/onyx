"""Integration tests for MANAGE_SERVICE_ACCOUNT_API_KEYS permission gate.

Covers the service-account API-key admin endpoints in
``backend/onyx/server/api_key/api.py`` (router prefix ``/admin/api-key``).
"""

import os
from typing import Any
from uuid import uuid4

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.permission_state import effective_permissions
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestUser,
    DATestUserGroup,
)
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

PERMISSION = Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS.value

_CREATE_API_KEY_BODY: dict[str, Any] = {
    "name": "perm-test-api-key",
    "group_ids": [],
}

ENDPOINTS: list[Endpoint] = [
    ("GET", "/admin/api-key", None),
    ("POST", "/admin/api-key", _CREATE_API_KEY_BODY),
    ("DELETE", "/admin/api-key/999999", None),
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


# ---------------------------------------------------------------------------
# Group assignment: a key's access is whatever its groups grant, so the picker lists
# every group and those grants must actually reach the key.
# ---------------------------------------------------------------------------


def test_holder_sees_default_groups(holder_user: DATestUser) -> None:
    # Everywhere else passes include_default as an admin, never as a plain holder.
    groups = UserGroupManager.get_all(
        user_performing_action=holder_user, include_default=True
    )
    names = {group.name for group in groups}
    assert {"Admin", "Basic"} <= names, names


def test_service_account_inherits_its_groups_permissions(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
) -> None:
    granting_group: DATestUserGroup = UserGroupManager.create(
        name=f"svc-acct-grant-{uuid4()}",
        user_performing_action=permission_admin_user,
    )
    UserGroupManager.set_permissions(
        user_group=granting_group,
        permissions=[Permission.MANAGE_LLMS.value],
        user_performing_action=permission_admin_user,
    ).raise_for_status()

    resp = call_endpoint(
        "POST",
        "/admin/api-key",
        {"name": f"perm-test-key-{uuid4()}", "group_ids": [granting_group.id]},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()

    assert Permission.MANAGE_LLMS.value in effective_permissions(created["user_id"])

    # intended: the permission is admin-equivalent, so a key may carry grants its
    # creator lacks
    key_headers = {"Authorization": f"Bearer {created['api_key']}"}
    assert_response(
        call_endpoint("GET", "/admin/llm/provider", None, key_headers, None),
        "GET",
        "/admin/llm/provider",
        "service_account_in_granting_group",
        "allowed",
    )
