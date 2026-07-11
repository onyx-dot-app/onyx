"""Integration tests for the mobile bearer-token auth gateway (PR 1).

Verifies that a native client can obtain / use / refresh / revoke the existing
session token as a Bearer (Authorization header) instead of the web cookie,
and that the web cookie flow is unaffected.
"""

from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.mobile_auth._helpers import bearer
from tests.integration.tests.mobile_auth._helpers import mobile_login


def test_mobile_bearer_login_refresh_logout(admin_user: DATestUser) -> None:
    # 1) Mobile login returns a Bearer token as JSON — and must NOT set the web
    #    auth cookie (a native client can't use HttpOnly cookies).
    resp = mobile_login(admin_user.email, admin_user.password)
    resp.raise_for_status()
    body = resp.json()
    assert body["token_type"].lower() == "bearer"
    token = body["access_token"]
    assert token
    assert FASTAPI_USERS_AUTH_COOKIE_NAME not in resp.cookies
    # The shared client jar must not carry a session cookie into later calls;
    # we authenticate purely via the Bearer header.
    client.cookies.clear()

    # 2) The Bearer token authenticates /me.
    me = client.get(url=f"{API_SERVER_URL}/me", headers=bearer(token))
    me.raise_for_status()
    assert me.json()["email"] == admin_user.email

    # 3) Refresh returns a usable token (redis/postgres extend the same token;
    #    either way the returned token must authenticate).
    refreshed = client.post(
        url=f"{API_SERVER_URL}/auth/mobile/refresh", headers=bearer(token)
    )
    refreshed.raise_for_status()
    new_token = refreshed.json()["access_token"]
    assert new_token
    client.cookies.clear()
    me2 = client.get(url=f"{API_SERVER_URL}/me", headers=bearer(new_token))
    me2.raise_for_status()

    # 4) Logout revokes the token server-side; reuse is rejected.
    logout = client.post(
        url=f"{API_SERVER_URL}/auth/mobile/logout", headers=bearer(new_token)
    )
    logout.raise_for_status()
    client.cookies.clear()
    # The revoked token must no longer authenticate (unauthenticated /me is
    # rejected — 403 in this deployment, 401 in others; both mean "rejected").
    me3 = client.get(url=f"{API_SERVER_URL}/me", headers=bearer(new_token))
    assert me3.status_code in (401, 403)


def test_mobile_bearer_login_bad_credentials(admin_user: DATestUser) -> None:
    resp = mobile_login(admin_user.email, "definitely-not-the-password")
    # fastapi-users returns 400 LOGIN_BAD_CREDENTIALS; accept 401 defensively.
    assert resp.status_code in (400, 401)
    assert "access_token" not in resp.json()


def test_web_cookie_login_still_works(admin_user: DATestUser) -> None:
    # Regression guard: adding the mobile bearer backend must not disturb the
    # existing web cookie login.
    headers = admin_user.headers.copy()
    headers.pop("Content-Type", None)
    resp = client.post(
        url=f"{API_SERVER_URL}/auth/login",
        data={"username": admin_user.email, "password": admin_user.password},
        headers=headers,
    )
    resp.raise_for_status()
    assert resp.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
    client.cookies.clear()
