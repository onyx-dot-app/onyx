"""Integration tests for password signup upgrade paths.

Verifies that when a BOT or EXT_PERM_USER user signs up via email/password:
- Their account_type is upgraded to STANDARD
- They are assigned to the Basic default group
- They gain the correct effective permissions
"""

import pytest

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
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


@pytest.mark.parametrize(
    "target_role",
    [UserRole.EXT_PERM_USER, UserRole.SLACK_USER],
    ids=["ext_perm_user", "slack_user"],
)
def test_password_signup_upgrade(
    reset: None,  # noqa: ARG001
    target_role: UserRole,
) -> None:
    """When a non-web user signs up via email/password, they should be
    upgraded to STANDARD account_type and assigned to the Basic default group."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = f"{target_role.value}_upgrade@example.com"
    test_user = UserManager.create(email=test_email)

    test_user = UserManager.set_role(
        user_to_set=test_user,
        target_role=target_role,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    # Verify user was removed from Basic group after downgrade
    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert (
        test_email not in basic_emails
    ), f"{target_role.value} should not be in Basic default group"

    # Re-register with the same email — triggers the password signup upgrade
    upgraded_user = UserManager.create(email=test_email)

    assert upgraded_user.role == UserRole.BASIC

    paginated = UserManager.get_user_page(
        user_performing_action=admin_user,
        page_num=0,
        page_size=10,
    )
    user_snapshot = next(
        (u for u in paginated.items if str(u.id) == upgraded_user.id), None
    )
    assert user_snapshot is not None
    assert (
        user_snapshot.account_type == AccountType.STANDARD
    ), f"Expected STANDARD, got {user_snapshot.account_type}"

    # Verify user is now in the Basic default group
    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert (
        test_email in basic_emails
    ), f"Upgraded user '{test_email}' not found in Basic default group"


def test_password_signup_upgrade_propagates_permissions(
    reset: None,  # noqa: ARG001
) -> None:
    """When an EXT_PERM_USER or SLACK_USER signs up via password, they should
    gain the 'basic' permission through the Basic default group assignment."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # --- EXT_PERM_USER path ---
    ext_email = "ext_perms_check@example.com"
    ext_user = UserManager.create(email=ext_email)

    initial_perms = UserManager.get_permissions(ext_user)
    assert "basic" in initial_perms

    ext_user = UserManager.set_role(
        user_to_set=ext_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert ext_email not in basic_emails

    upgraded = UserManager.create(email=ext_email)
    assert upgraded.role == UserRole.BASIC

    perms = UserManager.get_permissions(upgraded)
    assert (
        "basic" in perms
    ), f"Upgraded EXT_PERM_USER should have 'basic' permission, got: {perms}"

    # --- SLACK_USER path ---
    slack_email = "slack_perms_check@example.com"
    slack_user = UserManager.create(email=slack_email)

    slack_user = UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert slack_email not in basic_emails

    upgraded = UserManager.create(email=slack_email)
    assert upgraded.role == UserRole.BASIC

    perms = UserManager.get_permissions(upgraded)
    assert (
        "basic" in perms
    ), f"Upgraded SLACK_USER should have 'basic' permission, got: {perms}"
