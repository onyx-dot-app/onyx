import os

import pytest
import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_user_conversion(reset: None) -> None:
    """
    Test that SAML login correctly converts users with non-authenticated roles
    (SLACK_USER or EXT_PERM_USER) to authenticated roles (BASIC).

    This test:
    1. Creates an admin and a regular user
    2. Changes the regular user's role to EXT_PERM_USER
    3. Simulates a SAML login by calling the test endpoint
    4. Verifies the user's role is converted to BASIC

    This tests the fix that ensures users with non-authenticated roles (SLACK_USER or EXT_PERM_USER)
    are properly converted to authenticated roles during SAML login.
    """
    # Create an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(email="admin@onyx-test.com")

    # Create a regular user that we'll convert to EXT_PERM_USER
    test_user_email = "ext_perm_user@example.com"
    test_user = UserManager.create(email=test_user_email)

    # Verify the user was created with BASIC role initially
    assert UserManager.is_role(test_user, UserRole.BASIC)

    # Change the user's role to EXT_PERM_USER using the UserManager
    UserManager.set_role(
        user_to_set=test_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    # Verify the user has EXT_PERM_USER role now
    assert UserManager.is_role(test_user, UserRole.EXT_PERM_USER)

    # Simulate SAML login by calling the test endpoint
    response = requests.post(
        f"{API_SERVER_URL}/manage/users/test-upsert-user",
        json={"email": test_user_email},
        headers=admin_user.headers,  # Use admin headers for authorization
    )
    response.raise_for_status()

    # Verify the response indicates the role changed to BASIC
    user_data = response.json()
    assert user_data["role"] == UserRole.BASIC.value

    # Verify user role was changed in the database
    assert UserManager.is_role(test_user, UserRole.BASIC)

    # Do the same test with SLACK_USER
    slack_user_email = "slack_user@example.com"
    slack_user = UserManager.create(email=slack_user_email)

    # Verify the user was created with BASIC role initially
    assert UserManager.is_role(slack_user, UserRole.BASIC)

    # Change the user's role to SLACK_USER
    UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    # Verify the user has SLACK_USER role
    assert UserManager.is_role(slack_user, UserRole.SLACK_USER)

    # Simulate SAML login again
    response = requests.post(
        f"{API_SERVER_URL}/manage/users/test-upsert-user",
        json={"email": slack_user_email},
        headers=admin_user.headers,
    )
    response.raise_for_status()

    # Verify the response indicates the role changed to BASIC
    user_data = response.json()
    assert user_data["role"] == UserRole.BASIC.value

    # Verify the user's role was changed in the database
    assert UserManager.is_role(slack_user, UserRole.BASIC)
