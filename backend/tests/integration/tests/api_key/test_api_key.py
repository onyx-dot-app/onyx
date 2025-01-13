import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


def test_limited(reset: None) -> None:
    """Verify that with a limited role key, limited endpoints are accessible and
    others are not."""

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
        user_performing_action=admin_user,
    )

    # test limited endpoint
    response = requests.get(
        f"{API_SERVER_URL}/persona/0",
        headers=api_key.headers,
    )
    assert response.status_code == 200

    # test admin endpoints
    response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=api_key.headers,
    )
    assert response.status_code == 403
