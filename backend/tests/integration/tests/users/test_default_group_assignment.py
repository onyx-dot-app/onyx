"""Integration tests for default group assignment on user registration.

Verifies that:
- The first registered user is assigned to the Admin default group
- Subsequent registered users are assigned to the Basic default group
- account_type is set to STANDARD for email/password registrations
"""

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def test_default_group_assignment_on_registration(reset: None) -> None:  # noqa: ARG001
    # Register first user — should become admin
    admin_user: DATestUser = UserManager.create(name="first_user")
    assert admin_user.role == UserRole.ADMIN

    # Register second user — should become basic
    basic_user: DATestUser = UserManager.create(name="second_user")
    assert basic_user.role == UserRole.BASIC

    # Fetch all groups including default ones
    all_groups = UserGroupManager.get_all(
        user_performing_action=admin_user,
        include_default=True,
    )

    # Find the default Admin and Basic groups
    admin_group = next(
        (g for g in all_groups if g.name == "Admin" and g.is_default), None
    )
    basic_group = next(
        (g for g in all_groups if g.name == "Basic" and g.is_default), None
    )
    assert admin_group is not None, "Admin default group not found"
    assert basic_group is not None, "Basic default group not found"

    # Verify admin user is in Admin group and NOT in Basic group
    admin_group_user_ids = {str(u.id) for u in admin_group.users}
    basic_group_user_ids = {str(u.id) for u in basic_group.users}

    assert (
        admin_user.id in admin_group_user_ids
    ), "First user should be in Admin default group"
    assert (
        admin_user.id not in basic_group_user_ids
    ), "First user should NOT be in Basic default group"

    # Verify basic user is in Basic group and NOT in Admin group
    assert (
        basic_user.id in basic_group_user_ids
    ), "Second user should be in Basic default group"
    assert (
        basic_user.id not in admin_group_user_ids
    ), "Second user should NOT be in Admin default group"

    # Verify account_type is STANDARD for both users via user listing API
    paginated_result = UserManager.get_user_page(
        user_performing_action=admin_user,
        page_num=0,
        page_size=10,
    )
    users_by_id = {str(u.id): u for u in paginated_result.items}

    admin_snapshot = users_by_id.get(admin_user.id)
    basic_snapshot = users_by_id.get(basic_user.id)
    assert admin_snapshot is not None, "Admin user not found in user listing"
    assert basic_snapshot is not None, "Basic user not found in user listing"

    assert (
        admin_snapshot.account_type == AccountType.STANDARD
    ), f"Admin user account_type should be STANDARD, got {admin_snapshot.account_type}"
    assert (
        basic_snapshot.account_type == AccountType.STANDARD
    ), f"Basic user account_type should be STANDARD, got {basic_snapshot.account_type}"
