"""The group-permission API accepts create:user_api_keys as a no-op. Basic access
implies it now, and Terraform configs written against the old registry still
send it, so the request must succeed without storing a grant."""

import os

import httpx
import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_legacy_pat_grant_is_noop(new_admin_user: DATestUser) -> None:
    user_group: DATestUserGroup = UserGroupManager.create(
        name="legacy-pat-grant-group",
        user_ids=[new_admin_user.id],
        user_performing_action=new_admin_user,
    )

    response: httpx.Response = UserGroupManager.set_permissions(
        user_group=user_group,
        permissions=[
            Permission.CREATE_USER_API_KEYS.value,
            Permission.READ_QUERY_HISTORY.value,
        ],
        user_performing_action=new_admin_user,
    )
    response.raise_for_status()

    permissions: list[str] = UserGroupManager.get_permissions(
        user_group=user_group,
        user_performing_action=new_admin_user,
        include_non_toggleable=True,
    )
    assert Permission.READ_QUERY_HISTORY.value in permissions
    assert Permission.CREATE_USER_API_KEYS.value not in permissions

    # A truly non-toggleable value is still rejected.
    rejected: httpx.Response = UserGroupManager.set_permissions(
        user_group=user_group,
        permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        user_performing_action=new_admin_user,
    )
    assert rejected.status_code == 400
