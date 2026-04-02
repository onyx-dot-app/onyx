import os

import pytest
import requests

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
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


def _get_basic_group_member_emails(admin_user: DATestUser) -> set[str]:
    """Get the set of emails of all members in the Basic default group."""
    all_groups = UserGroupManager.get_all(admin_user, include_default=True)
    basic_default = [g for g in all_groups if g.is_default and g.name == "Basic"]
    assert basic_default, "Basic default group not found"
    return {u.email for u in basic_default[0].users}


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_user_conversion(reset: None) -> None:  # noqa: ARG001
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
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

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
    user_data = _simulate_saml_login(test_user_email, admin_user)

    # Verify the response indicates the role changed to BASIC
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
    user_data = _simulate_saml_login(slack_user_email, admin_user)

    # Verify the response indicates the role changed to BASIC
    assert user_data["role"] == UserRole.BASIC.value

    # Verify the user's role was changed in the database
    assert UserManager.is_role(slack_user, UserRole.BASIC)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_user_conversion_sets_account_type_and_group(
    reset: None,  # noqa: ARG001
) -> None:
    """
    Test that SAML login sets account_type to STANDARD when converting a
    non-web user (EXT_PERM_USER) and that the user receives the correct role
    (BASIC) after conversion.

    This validates the permissions-migration-phase2 changes which ensure that:
    1. account_type is updated to 'standard' on SAML conversion
    2. The converted user is assigned to the Basic default group
    """
    # Create an admin user (first user is automatically admin)
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # Create a user and set them as EXT_PERM_USER
    test_email = "ext_convert@example.com"
    test_user = UserManager.create(email=test_email)
    UserManager.set_role(
        user_to_set=test_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert UserManager.is_role(test_user, UserRole.EXT_PERM_USER)

    # Simulate SAML login
    user_data = _simulate_saml_login(test_email, admin_user)

    # Verify account_type is set to standard after conversion
    assert (
        user_data["account_type"] == AccountType.STANDARD.value
    ), f"Expected account_type='{AccountType.STANDARD.value}', got '{user_data['account_type']}'"

    # Verify role is BASIC after conversion
    assert user_data["role"] == UserRole.BASIC.value

    # Verify the user was assigned to the Basic default group
    assert test_email in _get_basic_group_member_emails(
        admin_user
    ), f"Converted user '{test_email}' not found in Basic default group"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_normal_signin_assigns_group(
    reset: None,  # noqa: ARG001
) -> None:
    """
    Test that a brand-new user signing in via SAML for the first time
    is created with the correct role, account_type, and group membership.

    This validates that normal SAML sign-in (not an upgrade from
    SLACK_USER/EXT_PERM_USER) correctly:
    1. Creates the user with role=BASIC and account_type=STANDARD
    2. Assigns the user to the Basic default group
    """
    # First user becomes admin
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # New user signs in via SAML (no prior account)
    new_email = "new_saml_user@example.com"
    user_data = _simulate_saml_login(new_email, admin_user)

    # Verify role and account_type
    assert user_data["role"] == UserRole.BASIC.value
    assert user_data["account_type"] == AccountType.STANDARD.value

    # Verify user is in the Basic default group
    assert new_email in _get_basic_group_member_emails(
        admin_user
    ), f"New SAML user '{new_email}' not found in Basic default group"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_user_conversion_restores_group_membership(
    reset: None,  # noqa: ARG001
) -> None:
    """
    Test that SAML login restores Basic group membership when converting
    a non-authenticated user (EXT_PERM_USER or SLACK_USER) to BASIC.

    Group membership implies 'basic' permission (verified by
    test_new_group_gets_basic_permission).
    """
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # --- EXT_PERM_USER path ---
    ext_email = "ext_perm_perms@example.com"
    ext_user = UserManager.create(email=ext_email)
    assert ext_email in _get_basic_group_member_emails(admin_user)

    UserManager.set_role(
        user_to_set=ext_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert ext_email not in _get_basic_group_member_emails(admin_user)

    user_data = _simulate_saml_login(ext_email, admin_user)
    assert user_data["role"] == UserRole.BASIC.value
    assert ext_email in _get_basic_group_member_emails(
        admin_user
    ), "EXT_PERM_USER should be back in Basic group after SAML conversion"

    # --- SLACK_USER path ---
    slack_email = "slack_perms@example.com"
    slack_user = UserManager.create(email=slack_email)

    UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert slack_email not in _get_basic_group_member_emails(admin_user)

    user_data = _simulate_saml_login(slack_email, admin_user)
    assert user_data["role"] == UserRole.BASIC.value
    assert slack_email in _get_basic_group_member_emails(
        admin_user
    ), "SLACK_USER should be back in Basic group after SAML conversion"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_round_trip_group_lifecycle(
    reset: None,  # noqa: ARG001
) -> None:
    """
    Test the full round-trip: BASIC -> EXT_PERM -> SAML(BASIC) -> EXT_PERM -> SAML(BASIC).

    Verifies group membership is correctly removed and restored at each transition.
    """
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = "roundtrip@example.com"
    test_user = UserManager.create(email=test_email)

    # Step 1: BASIC user is in Basic group
    assert test_email in _get_basic_group_member_emails(admin_user)

    # Step 2: Downgrade to EXT_PERM_USER — loses Basic group
    UserManager.set_role(
        user_to_set=test_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert test_email not in _get_basic_group_member_emails(admin_user)

    # Step 3: SAML login — converts back to BASIC, regains Basic group
    _simulate_saml_login(test_email, admin_user)
    assert test_email in _get_basic_group_member_emails(
        admin_user
    ), "Should be in Basic group after first SAML conversion"

    # Step 4: Downgrade again
    UserManager.set_role(
        user_to_set=test_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert test_email not in _get_basic_group_member_emails(admin_user)

    # Step 5: SAML login again — should still restore correctly
    _simulate_saml_login(test_email, admin_user)
    assert test_email in _get_basic_group_member_emails(
        admin_user
    ), "Should be in Basic group after second SAML conversion"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="SAML tests are enterprise only",
)
def test_saml_slack_user_conversion_sets_account_type_and_group(
    reset: None,  # noqa: ARG001
) -> None:
    """
    Test that SAML login sets account_type to STANDARD and assigns Basic group
    when converting a SLACK_USER (BOT account_type).

    Mirrors test_saml_user_conversion_sets_account_type_and_group but for
    SLACK_USER instead of EXT_PERM_USER, and additionally verifies permissions.
    """
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    test_email = "slack_convert@example.com"
    test_user = UserManager.create(email=test_email)

    UserManager.set_role(
        user_to_set=test_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert UserManager.is_role(test_user, UserRole.SLACK_USER)

    # SAML login
    user_data = _simulate_saml_login(test_email, admin_user)

    # Verify account_type and role
    assert (
        user_data["account_type"] == AccountType.STANDARD.value
    ), f"Expected STANDARD, got {user_data['account_type']}"
    assert user_data["role"] == UserRole.BASIC.value

    # Verify Basic group membership (implies 'basic' permission)
    assert test_email in _get_basic_group_member_emails(
        admin_user
    ), f"Converted SLACK_USER '{test_email}' not found in Basic default group"
