from uuid import uuid4

from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

INVITED_BASIC_USER = "basic_user"
INVITED_BASIC_USER_EMAIL = "basic_user@example.com"


def test_admin_can_invite_users(reset_multitenant: None) -> None:  # noqa: ARG001
    """Test that an admin can invite both registered and non-registered users."""
    # Create first user (admin)
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_admin(admin_user)

    # Second registered user in a fresh tenant is also admin (first user of their tenant)
    invited_user: DATestUser = UserManager.create(name=f"admin_invited_{unique}")
    assert UserManager.is_admin(invited_user)

    # Admin user invites the previously registered and non-registered user
    UserManager.invite_user(invited_user.email, admin_user)
    UserManager.invite_user(f"{INVITED_BASIC_USER}_{unique}@example.com", admin_user)

    # Verify users are in the invited users list
    invited_users = UserManager.get_invited_users(admin_user)
    assert invited_user.email in [user.email for user in invited_users], (
        f"User {invited_user.email} not found in invited users list"
    )


def test_non_registered_user_gets_basic_role(
    reset_multitenant: None,  # noqa: ARG001
) -> None:
    """Test that a non-registered user gets a BASIC role when they register after being invited."""
    # Create admin user
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_admin(admin_user)

    # Admin user invites a non-registered user
    invited_email = f"{INVITED_BASIC_USER}_{unique}@example.com"
    UserManager.invite_user(invited_email, admin_user)

    # Non-registered user registers
    invited_basic_user: DATestUser = UserManager.create(
        name=f"{INVITED_BASIC_USER}_{unique}", email=invited_email
    )
    assert not UserManager.is_admin(invited_basic_user)


def test_user_can_accept_invitation(
    reset_multitenant: None,  # noqa: ARG001
) -> None:  # noqa: ARG001
    """Test that a user can accept an invitation and join the organization with BASIC role."""
    # Create admin user
    unique = uuid4().hex
    admin_user: DATestUser = UserManager.create(name=f"admin_{unique}")
    assert UserManager.is_admin(admin_user)

    # Create a user to be invited
    invited_user_email = f"invited_user_{unique}@example.com"

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

    # Verify the user lands with a STANDARD account and without admin privileges
    assert updated_user_info.account_type == AccountType.STANDARD
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value not in (
        updated_user_info.effective_permissions or []
    )

    # Verify user is visible in the admin users listing for the tenant
    user_page = UserManager.get_user_page(user_performing_action=admin_user)

    invited_user_emails = [user.email for user in user_page.items]
    assert invited_user_email in invited_user_emails, (
        f"User {invited_user_email} not found in the organization listing. "
        f"Available users: {invited_user_emails}"
    )

    invited_users = UserManager.get_invited_users(admin_user)
    assert invited_user.email not in [user.email for user in invited_users], (
        f"User {invited_user.email} should not be found in invited users list after accepting invitation"
    )
