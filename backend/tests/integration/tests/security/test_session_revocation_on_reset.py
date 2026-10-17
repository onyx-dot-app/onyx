"""A password reset or change signs out the user's existing sessions."""

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

ME_URL = f"{API_SERVER_URL}/me"
ADMIN_RESET_URL = f"{API_SERVER_URL}/password/reset_password"
CHANGE_URL = f"{API_SERVER_URL}/password/change-password"


def _me_status(user: DATestUser) -> int:
    return client.get(ME_URL, headers=user.headers, timeout=30).status_code


def _second_session(user: DATestUser) -> DATestUser:
    return UserManager.login_as_user(user.model_copy(deep=True))


def test_admin_reset_revokes_all_target_sessions(admin_user: DATestUser) -> None:
    target = UserManager.create()
    other_session = _second_session(target)
    assert _me_status(target) == 200
    assert _me_status(other_session) == 200

    response = client.post(
        ADMIN_RESET_URL,
        json={"user_email": target.email},
        headers=admin_user.headers,
        timeout=30,
    )
    assert response.status_code == 200, response.text

    assert _me_status(target) in (401, 403)
    assert _me_status(other_session) in (401, 403)
    assert _me_status(admin_user) == 200

    target.password = response.json()["new_password"]
    assert _me_status(UserManager.login_as_user(target)) == 200


def test_admin_cannot_reset_own_password(admin_user: DATestUser) -> None:
    response = client.post(
        ADMIN_RESET_URL,
        json={"user_email": admin_user.email},
        headers=admin_user.headers,
        timeout=30,
    )
    assert response.status_code == 400, response.text
    assert _me_status(admin_user) == 200


def test_change_password_keeps_current_session_only() -> None:
    user = UserManager.create()
    other_session = _second_session(user)
    new_password = "Changed-Passw0rd-123!"

    response = client.post(
        CHANGE_URL,
        json={"old_password": user.password, "new_password": new_password},
        headers=user.headers,
        timeout=30,
    )
    assert response.status_code == 200, response.text

    assert _me_status(user) == 200
    assert _me_status(other_session) in (401, 403)
