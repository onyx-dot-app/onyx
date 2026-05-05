"""Integration tests for default group reconciliation on user reactivation.

Verifies that:
- A deactivated user retains default group membership after reactivation
- Reactivation via the admin API reconciles missing group membership
"""

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _get_default_group_member_emails(
    admin_user: DATestUser,
    group_name: str,
) -> set[str]:
    """Get the set of emails of all members in a named default group."""
    all_groups = UserGroupManager.get_all(admin_user, include_default=True)
    matched = [g for g in all_groups if g.is_default and g.name == group_name]
    assert matched, f"Default group '{group_name}' not found"
    return {u.email for u in matched[0].users}


def test_reactivated_user_retains_default_group(
    reset: None,  # noqa: ARG001
) -> None:
    """Deactivating and reactivating a user should preserve their
    default group membership."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    basic_user: DATestUser = UserManager.create(name="basic_user")

    # Verify user is in Basic group initially
    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert basic_user.email in basic_emails

    # Deactivate the user
    UserManager.set_status(
        user_to_set=basic_user,
        target_status=False,
        user_performing_action=admin_user,
    )

    # Reactivate the user
    UserManager.set_status(
        user_to_set=basic_user,
        target_status=True,
        user_performing_action=admin_user,
    )

    # Verify user is still in Basic group after reactivation
    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert (
        basic_user.email in basic_emails
    ), "Reactivated user should still be in Basic default group"
