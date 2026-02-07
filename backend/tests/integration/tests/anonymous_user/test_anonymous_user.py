import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def test_anonymous_user_access(reset: None) -> None:  # noqa: ARG001
    """Verify that anonymous users can access limited endpoints when enabled."""

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Enable anonymous user access
    SettingsManager.update_settings(
        DATestSettings(anonymous_user_enabled=True),
        user_performing_action=admin_user,
    )

    # Get anonymous user
    anon_user = UserManager.get_anonymous_user()

    # Verify anonymous user has LIMITED role
    assert anon_user.role == UserRole.LIMITED

    # Anonymous user should be able to access chat-related endpoints
    # (when anonymous access is enabled)
    response = requests.get(
        f"{API_SERVER_URL}/persona",
        headers=anon_user.headers,
    )
    assert response.status_code == 200


def test_anonymous_user_denied_when_disabled(reset: None) -> None:  # noqa: ARG001
    """Verify that anonymous users cannot access endpoints when disabled."""

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Ensure anonymous user access is disabled
    SettingsManager.update_settings(
        DATestSettings(anonymous_user_enabled=False),
        user_performing_action=admin_user,
    )

    # Get anonymous user (no auth cookies)
    anon_user = UserManager.get_anonymous_user()

    # Anonymous user should be denied access when anonymous access is disabled
    response = requests.get(
        f"{API_SERVER_URL}/persona",
        headers=anon_user.headers,
    )
    assert response.status_code == 401
