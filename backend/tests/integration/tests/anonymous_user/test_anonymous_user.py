import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def test_me_endpoint_returns_anonymous_user_when_enabled(
    reset: None,  # noqa: ARG001
) -> None:
    """Unauthenticated /me returns anonymous user info when anonymous access is enabled."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    SettingsManager.update_settings(
        DATestSettings(anonymous_user_enabled=True),
        user_performing_action=admin_user,
    )

    response = requests.get(f"{API_SERVER_URL}/me")

    assert response.status_code == 200
    data = response.json()
    assert data["is_anonymous_user"] is True
    assert data["email"] == "anonymous@onyx.app"
    assert data["role"] == "limited"


def test_me_endpoint_returns_403_when_anonymous_disabled(
    reset: None,  # noqa: ARG001
) -> None:
    """Unauthenticated /me returns 403 when anonymous access is disabled."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    SettingsManager.update_settings(
        DATestSettings(anonymous_user_enabled=False),
        user_performing_action=admin_user,
    )

    response = requests.get(f"{API_SERVER_URL}/me")

    # 403 is returned when user is not authenticated
    assert response.status_code == 403


def test_me_endpoint_returns_authenticated_user_info(
    reset: None,  # noqa: ARG001
) -> None:
    """Authenticated /me returns the actual user's info."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    response = requests.get(
        f"{API_SERVER_URL}/me",
        headers=admin_user.headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("is_anonymous_user") is not True
    assert data["email"] == admin_user.email
    assert data["role"] == "admin"
