"""Integration tests for SAML login user-conversion behaviour.

The SAML login path must convert users with non-web account types
(``BOT`` / ``EXT_PERM_USER``) into fully authenticated STANDARD users and
restore Basic default-group membership. We seed the non-web users directly
via the internal DB helpers used by the Slack bot and external permissions
sync pipelines — no admin API downgrades a user any more.
"""

import os

import pytest
import requests

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from onyx.db.users import get_user_by_email
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _simulate_saml_login(email: str, admin_user: DATestUser) -> dict:
    """Simulate a SAML login by calling the test upsert endpoint."""
    response = requests.post(
        f"{API_SERVER_URL}/manage/users/test-upsert-user",
        json={"email": email},
        headers=admin_user.headers,
    )
    response.raise_for_status()
    return response.json()


def _seed_non_web_user(account_type: AccountType, email: str) -> None:
    """Create a BOT or EXT_PERM_USER directly via the internal DB path."""
    with get_session_with_current_tenant() as db_session:
        if account_type == AccountType.BOT:
            add_slack_user_if_not_exists(db_session, email=email)
        elif account_type == AccountType.EXT_PERM_USER:
            batch_add_ext_perm_user_if_not_exists(db_session, emails=[email])
        else:
            raise ValueError(f"Unsupported seed account_type: {account_type}")


def _get_basic_group_member_emails(admin_user: DATestUser) -> set[str]:
    """Get the set of emails of all members in the Basic default group."""
    all_groups = UserGroupManager.get_all(admin_user, include_default=True)
    basic_default = [g for g in all_groups if g.is_default and g.name == "Basic"]
    assert basic_default, "Basic default group not found"
    return {u.email for u in basic_default[0].users}


def _get_effective_permissions(email: str) -> list[str]:
    """Read a user's stored effective_permissions directly from the DB."""
    with get_session_with_current_tenant() as db_session:
        user = get_user_by_email(email, db_session)
        assert user is not None, f"User '{email}' not found"
        return list(user.effective_permissions or [])


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
@pytest.mark.parametrize(
    "seeded_account_type",
    [AccountType.EXT_PERM_USER, AccountType.BOT],
    ids=["ext_perm_user", "slack_user"],
)
def test_saml_converts_non_web_user(
    reset: None,  # noqa: ARG001
    seeded_account_type: AccountType,
) -> None:
    """SAML login converts a non-web user (BOT or EXT_PERM_USER) to STANDARD."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = f"{seeded_account_type.value}_saml@example.com"
    _seed_non_web_user(seeded_account_type, test_email)

    # Pre-condition: non-web users are not in Basic default group
    assert test_email not in _get_basic_group_member_emails(admin_user)

    user_data = _simulate_saml_login(test_email, admin_user)
    assert user_data["account_type"] == AccountType.STANDARD.value
    assert test_email in _get_basic_group_member_emails(
        admin_user
    ), f"Converted user '{test_email}' not found in Basic default group"
    assert Permission.BASIC_ACCESS.value in _get_effective_permissions(test_email)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_normal_signin_assigns_group(
    reset: None,  # noqa: ARG001
) -> None:
    """A brand-new SAML signin creates a STANDARD user in the Basic group."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    new_email = "new_saml_user@example.com"
    user_data = _simulate_saml_login(new_email, admin_user)

    assert user_data["account_type"] == AccountType.STANDARD.value
    assert new_email in _get_basic_group_member_emails(
        admin_user
    ), f"New SAML user '{new_email}' not found in Basic default group"
    assert Permission.BASIC_ACCESS.value in _get_effective_permissions(new_email)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_idempotent_for_converted_user(
    reset: None,  # noqa: ARG001
) -> None:
    """Running SAML login twice on a converted user is idempotent — they stay
    STANDARD and remain in the Basic default group."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = "saml_idempotent@example.com"
    _seed_non_web_user(AccountType.EXT_PERM_USER, test_email)

    first = _simulate_saml_login(test_email, admin_user)
    assert first["account_type"] == AccountType.STANDARD.value
    assert test_email in _get_basic_group_member_emails(admin_user)
    assert Permission.BASIC_ACCESS.value in _get_effective_permissions(test_email)

    second = _simulate_saml_login(test_email, admin_user)
    assert second["account_type"] == AccountType.STANDARD.value
    assert test_email in _get_basic_group_member_emails(admin_user)
    assert Permission.BASIC_ACCESS.value in _get_effective_permissions(test_email)
