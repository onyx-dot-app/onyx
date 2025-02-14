import pytest
from requests import HTTPError

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_inviting_users_flow(reset: None) -> None:
    """
    Test that verifies the functionality around inviting users:
      1. Creating an admin user
      2. Admin inviting a new user
      3. Invited user successfully signing in
      4. Non-invited user attempting to sign in (should result in an error)
    """
    # 1) Create an admin user (the first user created is automatically admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert admin_user is not None
    assert UserManager.is_role(
        admin_user, UserRole.ADMIN
    ), "Admin user should have ADMIN role"

    # 2) Admin invites a new user
    invited_email = "invited_user@test.com"
    invite_response = UserManager.invite_users(admin_user, [invited_email])
    # The endpoint might return the count of successfully invited users or something similar.
    # Check that the invite was successful (this is just an example assertion).
    assert (
        invite_response == 1
    ), "Invite operation should return count=1 for a single invited user"

    # 3) The invited user successfully registers/logs in
    #    (In some implementations, the user might need to sign up with the invited email.)
    invited_user: DATestUser = UserManager.create(
        name="invited_user", email=invited_email
    )
    assert invited_user is not None, "Invited user should be able to register"
    assert invited_user.email == invited_email, "Invited user email mismatch"
    assert UserManager.is_role(
        invited_user, UserRole.BASIC
    ), "Newly created user should have BASIC role by default"

    # 4) A non-invited user attempts to sign in/register (should fail)
    with pytest.raises(HTTPError):
        UserManager.create(name="uninvited_user", email="uninvited_user@test.com")
