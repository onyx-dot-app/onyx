import os

import pytest

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_new_group_gets_basic_permission(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_for_basic_perm")

    user_group = UserGroupManager.create(
        name="basic-perm-test-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    permissions = UserGroupManager.get_permissions(
        user_group=user_group,
        user_performing_action=admin_user,
    )

    assert (
        "basic" in permissions
    ), f"New group should have 'basic' permission, got: {permissions}"
