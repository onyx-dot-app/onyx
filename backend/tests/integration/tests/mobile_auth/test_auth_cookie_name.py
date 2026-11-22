"""A native app learns the session cookie name from /auth/type, and a bearer
token set under that name signs the web UI in."""

from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.mobile_auth._helpers import mobile_login


def test_auth_type_reports_the_session_cookie_name(admin_user: DATestUser) -> None:
    auth_type = client.get(url=f"{API_SERVER_URL}/auth/type")
    auth_type.raise_for_status()
    name = auth_type.json()["auth_cookie_name"]
    assert name == FASTAPI_USERS_AUTH_COOKIE_NAME

    login = mobile_login(admin_user.email, admin_user.password)
    login.raise_for_status()
    token = login.json()["access_token"]
    client.cookies.clear()

    me = client.get(url=f"{API_SERVER_URL}/me", cookies={name: token})
    me.raise_for_status()
    assert me.json()["email"] == admin_user.email
