"""Integration tests for the curator-or-admin gate on connector read endpoints.

``GET /manage/connector`` (list) and ``GET /manage/connector/{id}`` (by-id) return
full ``ConnectorSnapshot``s including ``connector_specific_config`` and
``credential_ids``. They must be restricted to curator/admin users
(pentest M8 / ENG-4249); basic users, limited service accounts, bot users,
external-permission users, and anonymous clients must be denied. Curator access
is covered in ``test_connector_permissions.py``.
"""

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser

# Connector read endpoints gated on current_curator_or_admin_user.
# The by-id path targets a non-existent id on purpose: the auth dependency runs
# before the handler, so denied users get 403 while an admin gets 404 -- both
# outcomes confirm the auth gate behaved correctly.
CONNECTOR_READ_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/manage/connector"),
    ("GET", "/manage/connector/1"),
]


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
def test_admin_user_allowed(
    method: str,
    path: str,
    permission_admin_user: DATestUser,
) -> None:
    """Admin users pass the curator-or-admin gate (200 for list, 404 for missing id)."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    assert resp.status_code not in (401, 403), (
        f"Admin should pass auth on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
def test_basic_user_denied(
    method: str,
    path: str,
    permission_basic_user: DATestUser,
) -> None:
    """Basic users must NOT read connector config/credential ids."""
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


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
def test_limited_service_account_denied(
    method: str,
    path: str,
    limited_service_account: DATestAPIKey,
) -> None:
    """Limited service accounts (no curator/admin role) should be denied."""
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


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
def test_bot_user_denied(
    method: str,
    path: str,
    bot_user_headers: dict[str, str],
) -> None:
    """Bot (SLACK_USER) accounts should be denied."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=bot_user_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Bot user should be denied on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
def test_ext_perm_user_denied(
    method: str,
    path: str,
    ext_perm_user_headers: dict[str, str],
) -> None:
    """External permission users should be denied."""
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=ext_perm_user_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"Ext perm user should be denied on {method} {path}, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", CONNECTOR_READ_ENDPOINTS)
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
