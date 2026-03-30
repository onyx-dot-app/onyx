import os

import pytest

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_user_gets_permissions_when_added_to_group(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_for_perm_test")
    basic_user: DATestUser = UserManager.create(name="basic_user_for_perm_test")

    # basic_user starts with permissions from default group assignment
    initial_permissions = UserManager.get_permissions(basic_user)
    assert "basic" in initial_permissions

    # Create a new group and add basic_user directly at creation
    UserGroupManager.create(
        name="perm-test-group",
        user_ids=[admin_user.id, basic_user.id],
        user_performing_action=admin_user,
    )

    # Verify user's effective_permissions updated after being added to group
    updated_permissions = UserManager.get_permissions(basic_user)
    assert "basic" in updated_permissions, (
        f"User should have 'basic' permission after being added to group, "
        f"got: {updated_permissions}"
    )
