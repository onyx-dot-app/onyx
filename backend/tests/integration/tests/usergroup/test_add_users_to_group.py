import os
from uuid import uuid4

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_add_users_to_group(reset: None) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_for_add_user")
    user_to_add: DATestUser = UserManager.create(name="basic_user_to_add")

    user_group: DATestUserGroup = UserGroupManager.create(
        name="add-user-test-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    updated_user_group = UserGroupManager.add_users(
        user_group=user_group,
        user_ids=[user_to_add.id],
        user_performing_action=admin_user,
    )

    fetched_user_groups = UserGroupManager.get_all(user_performing_action=admin_user)
    fetched_user_group = next(
        group for group in fetched_user_groups if group.id == updated_user_group.id
    )

    fetched_user_ids = {user.id for user in fetched_user_group.users}
    assert admin_user.id in fetched_user_ids
    assert user_to_add.id in fetched_user_ids


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_add_users_to_group_invalid_user(reset: None) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_for_add_user_invalid")

    user_group: DATestUserGroup = UserGroupManager.create(
        name="add-user-invalid-test-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    invalid_user_id = str(uuid4())
    response = requests.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{user_group.id}/add-users",
        json={"user_ids": [invalid_user_id]},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )

    assert response.status_code == 404
    assert "not found" in response.text.lower()
