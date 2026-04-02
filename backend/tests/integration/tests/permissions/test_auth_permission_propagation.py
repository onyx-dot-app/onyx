"""Integration tests for permission propagation across auth-triggered group changes.

These tests verify that effective permissions (via /me/permissions) actually
propagate when users are added/removed from default groups through role changes.
Custom permission grant tests will be added once the permission grant API is built.
"""

import os

import pytest

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _get_basic_group_member_emails(admin_user: DATestUser) -> set[str]:
    all_groups = UserGroupManager.get_all(admin_user, include_default=True)
    basic_group = next(
        (g for g in all_groups if g.is_default and g.name == "Basic"), None
    )
    assert basic_group is not None, "Basic default group not found"
    return {u.email for u in basic_group.users}


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission propagation tests require enterprise features",
)
def test_basic_permission_granted_on_registration(
    reset: None,  # noqa: ARG001
) -> None:
    """New users should get 'basic' permission through default group assignment."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")
    basic_user: DATestUser = UserManager.create(email="basic@example.com")

    # Admin should have permissions from Admin group
    admin_perms = UserManager.get_permissions(admin_user)
    assert "basic" in admin_perms

    # Basic user should have 'basic' from Basic default group
    basic_perms = UserManager.get_permissions(basic_user)
    assert "basic" in basic_perms

    # Verify group membership matches
    assert basic_user.email in _get_basic_group_member_emails(admin_user)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission propagation tests require enterprise features",
)
def test_role_downgrade_removes_basic_group_and_permission(
    reset: None,  # noqa: ARG001
) -> None:
    """Downgrading to EXT_PERM_USER or SLACK_USER should remove from Basic group."""
    admin_user: DATestUser = UserManager.create(email="admin@example.com")

    # --- EXT_PERM_USER ---
    ext_user: DATestUser = UserManager.create(email="ext@example.com")
    assert ext_user.email in _get_basic_group_member_emails(admin_user)

    UserManager.set_role(
        user_to_set=ext_user,
        target_role=UserRole.EXT_PERM_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert ext_user.email not in _get_basic_group_member_emails(admin_user)

    # --- SLACK_USER ---
    slack_user: DATestUser = UserManager.create(email="slack@example.com")
    assert slack_user.email in _get_basic_group_member_emails(admin_user)

    UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert slack_user.email not in _get_basic_group_member_emails(admin_user)
