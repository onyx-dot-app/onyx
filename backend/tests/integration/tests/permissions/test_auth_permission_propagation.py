"""Integration tests for permission propagation via default-group assignment.

Verifies that effective permissions (via /me/permissions) actually propagate
when users are created through the standard web-signup path (which assigns
them to the Basic default group).

Note: the legacy "downgrade to EXT_PERM_USER/SLACK_USER via admin API"
scenario has been removed — non-web account types can only be created via
the internal Slack/external-permissions sync paths and are covered in
``test_password_signup_upgrade.py``.
"""

import os

import pytest

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
    """New users gain 'basic' permission through default group assignment."""
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
