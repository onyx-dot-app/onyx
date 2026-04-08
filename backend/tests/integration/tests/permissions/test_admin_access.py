"""Integration tests for FULL_ADMIN_PANEL_ACCESS permission gate.

Verifies that endpoints protected by
``require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)``
allow admin users but reject basic users, limited service accounts,
bot users, external-permission users, and anonymous (unauthenticated) requests.

Each endpoint is tested with all six user types via parameterization.
"""

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
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
    resp = requests.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    assert (
        resp.status_code < 400
    ), f"Admin should access {method} {path}, got {resp.status_code}"


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
    resp = requests.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=permission_basic_user.headers,
        cookies=permission_basic_user.cookies,
        timeout=30,
    )
    assert (
        resp.status_code == 403
    ), f"Basic user should be denied on {method} {path}, got {resp.status_code}"


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_limited_service_account_denied(
    method: str,
    path: str,
    limited_service_account: DATestAPIKey,
) -> None:
    """Limited service accounts (no FULL_ADMIN_PANEL_ACCESS) should be denied."""
    resp = requests.request(
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
    resp = requests.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=bot_user_headers,
        timeout=30,
    )
    assert (
        resp.status_code == 403
    ), f"Bot user should be denied on {method} {path}, got {resp.status_code}"


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_ext_perm_user_denied(
    method: str,
    path: str,
    ext_perm_user_headers: dict[str, str],
) -> None:
    """External permission users should be denied from admin endpoints."""
    resp = requests.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=ext_perm_user_headers,
        timeout=30,
    )
    assert (
        resp.status_code == 403
    ), f"Ext perm user should be denied on {method} {path}, got {resp.status_code}"


@pytest.mark.parametrize("method,path", ADMIN_ACCESS_ENDPOINTS)
def test_anonymous_denied(
    method: str,
    path: str,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures reset ran
) -> None:
    """Unauthenticated (anonymous) requests should be denied."""
    resp = requests.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers={},
        timeout=30,
    )
    assert resp.status_code in (
        401,
        403,
    ), f"Anonymous should be denied on {method} {path}, got {resp.status_code}"
