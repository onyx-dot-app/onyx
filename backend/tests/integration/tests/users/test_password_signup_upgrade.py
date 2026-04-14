"""Integration tests for password signup upgrade paths.

Verifies that when a BOT or EXT_PERM_USER user signs up via email/password:
- Their account_type is upgraded to STANDARD
- They are assigned to the Basic default group
- They gain the correct effective permissions

Non-web users are seeded directly via the internal DB helpers
(``add_slack_user_if_not_exists`` / ``batch_add_ext_perm_user_if_not_exists``)
since no admin-facing downgrade API exists any more.
"""

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _seed_non_web_user(account_type: AccountType, email: str) -> None:
    """Seed a BOT or EXT_PERM_USER account directly via the db helpers."""
    with get_session_with_current_tenant() as db_session:
        if account_type == AccountType.BOT:
            add_slack_user_if_not_exists(db_session, email=email)
        elif account_type == AccountType.EXT_PERM_USER:
            batch_add_ext_perm_user_if_not_exists(db_session, emails=[email])
        else:
            raise ValueError(f"Unsupported seed account_type: {account_type}")


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
    "seeded_account_type",
    [AccountType.EXT_PERM_USER, AccountType.BOT],
    ids=["ext_perm_user", "slack_user"],
)
def test_password_signup_upgrade(
    reset: None,  # noqa: ARG001
    seeded_account_type: AccountType,
) -> None:
    """A non-web user who signs up via password is upgraded to STANDARD and
    assigned to the Basic default group."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = f"{seeded_account_type.value}_upgrade@example.com"
    _seed_non_web_user(seeded_account_type, test_email)

    # Non-web users should not be in the Basic default group before upgrade
    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert test_email not in basic_emails

    # Register with the same email — triggers the password signup upgrade
    upgraded_user = UserManager.create(email=test_email)

    assert not upgraded_user.is_admin

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

    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert (
        test_email in basic_emails
    ), f"Upgraded user '{test_email}' not found in Basic default group"


def test_password_signup_upgrade_propagates_permissions(
    reset: None,  # noqa: ARG001
) -> None:
    """A non-web user who signs up via password gains the 'basic' permission
    through the Basic default group assignment."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # --- EXT_PERM_USER path ---
    ext_email = "ext_perms_check@example.com"
    _seed_non_web_user(AccountType.EXT_PERM_USER, ext_email)

    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert ext_email not in basic_emails

    upgraded = UserManager.create(email=ext_email)
    assert not upgraded.is_admin

    perms = UserManager.get_permissions(upgraded)
    assert (
        "basic" in perms
    ), f"Upgraded EXT_PERM_USER should have 'basic' permission, got: {perms}"

    # --- BOT (Slack) path ---
    slack_email = "slack_perms_check@example.com"
    _seed_non_web_user(AccountType.BOT, slack_email)

    basic_emails = _get_default_group_member_emails(admin_user, "Basic")
    assert slack_email not in basic_emails

    upgraded = UserManager.create(email=slack_email)
    assert not upgraded.is_admin

    perms = UserManager.get_permissions(upgraded)
    assert (
        "basic" in perms
    ), f"Upgraded SLACK_USER should have 'basic' permission, got: {perms}"
