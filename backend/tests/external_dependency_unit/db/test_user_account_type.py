"""
Tests that account_type is correctly set when creating users through
the internal DB functions: add_slack_user_if_not_exists and
batch_add_ext_perm_user_if_not_exists.

These functions are called by background workers (Slack bot, permission sync)
and are not exposed via API endpoints, so they must be tested directly.
"""

from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.models import UserRole
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists


def test_slack_user_creation_sets_account_type_bot(db_session: Session) -> None:
    """add_slack_user_if_not_exists sets account_type=BOT and role=SLACK_USER."""
    user = add_slack_user_if_not_exists(db_session, "slack_acct_type@test.com")

    assert user.role == UserRole.SLACK_USER
    assert user.account_type == AccountType.BOT


def test_ext_perm_user_creation_sets_account_type(db_session: Session) -> None:
    """batch_add_ext_perm_user_if_not_exists sets account_type=EXT_PERM_USER."""
    users = batch_add_ext_perm_user_if_not_exists(
        db_session, ["extperm_acct_type@test.com"]
    )

    assert len(users) == 1
    user = users[0]
    assert user.role == UserRole.EXT_PERM_USER
    assert user.account_type == AccountType.EXT_PERM_USER


def test_ext_perm_to_slack_upgrade_updates_role(db_session: Session) -> None:
    """When an EXT_PERM_USER is upgraded to slack, role becomes SLACK_USER.

    Note: currently account_type is NOT updated during this upgrade path —
    it remains EXT_PERM_USER. This test documents the current behaviour.
    """
    email = "ext_to_slack_acct_type@test.com"

    # Create as ext_perm user first
    batch_add_ext_perm_user_if_not_exists(db_session, [email])

    # Now "upgrade" via slack path
    user = add_slack_user_if_not_exists(db_session, email)

    assert user.role == UserRole.SLACK_USER
    # Documents current gap: account_type stays EXT_PERM_USER after upgrade
    assert user.account_type == AccountType.EXT_PERM_USER
