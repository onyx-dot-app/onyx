from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def test_limited(reset: None) -> None:
    """Verify that with a limited role key, limited endpoints are accessible and
    others are not."""

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")
    SettingsManager.update_settings(DATestSettings(anonymous_user_enabled=True))
    print(admin_user.headers)
