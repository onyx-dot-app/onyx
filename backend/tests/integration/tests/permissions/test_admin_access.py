"""Integration tests for FULL_ADMIN_PANEL_ACCESS permission gate.

Verifies that endpoints protected by
``require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)``
allow admin users but reject basic users, limited service accounts,
bot users, external-permission users, and anonymous (unauthenticated) client.

Each endpoint is tested with all six user types via parameterization.
"""

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser

# Representative endpoints that use require_permission(Permission.FULL_ADMIN_PANEL_ACCESS).
# One per major router file to cover breadth without redundancy.
ADMIN_ACCESS_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/admin/token-rate-limits/global"),
    ("GET", "/manage/users/counts"),
    ("GET", "/manage/users/invited"),
    ("GET", "/manage/admin/valid-domains"),
    ("GET", "/manage/users/download"),
]


# ------------------------------------------------------------------
# Allowed users: admin only
# ------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_admin_user_allowed(
    method: str,
    path: str,
    permission_admin_user: DATestUser,
) -> None:
    """Admin users should be able to access FULL_ADMIN_PANEL_ACCESS endpoints."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    assert resp.status_code < 400, (
        f"Admin should access {method} {path}, got {resp.status_code}"
    )


# ------------------------------------------------------------------
# Denied users: basic, limited service account, bot, ext_perm, anonymous
# ------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_basic_user_denied(
    method: str,
    path: str,
    permission_basic_user: DATestUser,
) -> None:
    """Basic users should NOT be able to access admin-only endpoints."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=permission_basic_user.headers,
        cookies=permission_basic_user.cookies,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Basic user should be denied on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_limited_service_account_denied(
    method: str,
    path: str,
    limited_service_account: DATestAPIKey,
) -> None:
    """Limited service accounts (no FULL_ADMIN_PANEL_ACCESS) should be denied."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=limited_service_account.headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Limited service account should be denied on {method} {path}, "
        f"got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_bot_user_denied(
    method: str,
    path: str,
    bot_user_headers: dict[str, str],
) -> None:
    """Bot (SLACK_USER) accounts should be denied from admin endpoints."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=bot_user_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Bot user should be denied on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_ext_perm_user_denied(
    method: str,
    path: str,
    ext_perm_user_headers: dict[str, str],
) -> None:
    """External permission users should be denied from admin endpoints."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=ext_perm_user_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Ext perm user should be denied on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_anonymous_denied(
    method: str,
    path: str,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures reset ran
) -> None:
    """Unauthenticated (anonymous) requests should be denied."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers={},
        timeout=30,
    )
    assert resp.status_code in (
        401,
        403,
    ), f"Anonymous should be denied on {method} {path}, got {resp.status_code}"


def test_basic_user_cannot_add_users_to_admin_group(
    permission_admin_user: DATestUser,
    permission_basic_user: DATestUser,
) -> None:
    """A basic user calling the MANAGE_USER_GROUPS-protected add-users
    endpoint on the Admin default group is rejected — the closest-still-alive
    replacement for the removed "basic cannot promote to GLOBAL_CURATOR"
    check from the deleted ``test_user_role_permissions.py``."""
    groups_response = client.get(
        f"{API_SERVER_URL}/manage/admin/user-group?include_default=true",
        headers=permission_admin_user.headers,
        timeout=30,
    )
    groups_response.raise_for_status()
    admin_group = next(
        (
            g
            for g in groups_response.json()
            if g.get("is_default") is True and g.get("name") == "Admin"
        ),
        None,
    )
    assert admin_group is not None, "Admin default group not found"

    resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{admin_group['id']}/add-users",
        json={"user_ids": [permission_basic_user.id]},
        headers=permission_basic_user.headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        "Basic user should not be able to add users to the Admin group, "
        f"got {resp.status_code}"
    )
