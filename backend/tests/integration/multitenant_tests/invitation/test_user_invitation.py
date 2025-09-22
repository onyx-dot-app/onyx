from uuid import uuid4

from onyx.db.models import UserRole
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

INVITED_BASIC_USER = "basic_user"
INVITED_BASIC_USER_EMAIL = "basic_user@test.com"


def test_admin_can_invite_users(reset_multitenant: None) -> None:
    """Test that an admin can invite both registered and non-registered users."""
    # Create first user (admin)
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    # Create second user
    invited_user: DATestUser = UserManager.create(name=f"admin_invited_{unique}")
    assert UserManager.is_role(invited_user, UserRole.ADMIN)

    # Admin user invites the previously registered and non-registered user
    UserManager.invite_user(invited_user.email, admin_user)
    UserManager.invite_user(f"{INVITED_BASIC_USER}+{unique}@test.com", admin_user)

    # Verify users are in the invited users list
    invited_users = UserManager.get_invited_users(admin_user)
    assert invited_user.email in [
        user.email for user in invited_users
    ], f"User {invited_user.email} not found in invited users list"


def test_non_registered_user_gets_basic_role(reset_multitenant: None) -> None:
    """Test that a non-registered user gets a BASIC role when they register after being invited."""
    # Create admin user
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    # Admin user invites a non-registered user
    invited_email = f"{INVITED_BASIC_USER}+{unique}@test.com"
    UserManager.invite_user(invited_email, admin_user)

    # Non-registered user registers
    invited_basic_user: DATestUser = UserManager.create(
        name=f"{INVITED_BASIC_USER}_{unique}", email=invited_email
    )
    assert UserManager.is_role(invited_basic_user, UserRole.BASIC)


def test_user_can_accept_invitation(reset_multitenant: None) -> None:
    """Test that a user can accept an invitation and join the organization with BASIC role."""
    # Create admin user
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    # Create a user to be invited
    invited_user_email = f"invited_user+{unique}@test.com"

    # User registers with the same email as the invitation
    invited_user: DATestUser = UserManager.create(
        name=f"invited_user_{unique}", email=invited_user_email
    )
    # Admin user invites the user
    UserManager.invite_user(invited_user_email, admin_user)

    # Get user info to check tenant information
    user_info = UserManager.get_user_info(invited_user)

    # Extract the tenant_id from the invitation
    invited_tenant_id = (
        user_info.tenant_info.invitation.tenant_id
        if user_info.tenant_info and user_info.tenant_info.invitation
        else None
    )
    assert invited_tenant_id is not None, "Expected to find an invitation tenant_id"

    # User accepts invitation
    UserManager.accept_invitation(invited_tenant_id, invited_user)

    # User needs to reauthenticate after accepting invitation
    # Simulate this by creating a new user instance with the same credentials
    authenticated_user: DATestUser = UserManager.create(
        name="invited_user", email=invited_user_email
    )

    # Get updated user info after accepting invitation and reauthenticating
    updated_user_info = UserManager.get_user_info(authenticated_user)

    # Verify the user has BASIC role in the organization
    assert (
        updated_user_info.role == UserRole.BASIC
    ), f"Expected user to have BASIC role, but got {updated_user_info.role}"

    # Verify user is in the organization
    user_page = UserManager.get_user_page(
        user_performing_action=admin_user, role_filter=[UserRole.BASIC]
    )

    # Check if the invited user is in the list of users with BASIC role
    invited_user_emails = [user.email for user in user_page.items]
    assert invited_user_email in invited_user_emails, (
        f"User {invited_user_email} not found in the list of basic users "
        f"in the organization. Available users: {invited_user_emails}"
    )

    invited_users = UserManager.get_invited_users(admin_user)
    assert invited_user.email not in [
        user.email for user in invited_users
    ], f"User {invited_user.email} should not be found in invited users list after accepting invitation"
