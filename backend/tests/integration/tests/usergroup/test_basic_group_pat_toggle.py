"""The seeded Basic group grants create:user_api_keys by default. An admin can switch
it off and back on, and nothing else can be toggled there."""

import os

import httpx
import pytest

from ee.onyx.server.user_group.models import UserGroup
from onyx.db.enums import Permission
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestPAT, DATestUser

PAT_PERMISSION = Permission.CREATE_USER_API_KEYS.value


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_basic_group_pat_toggle(new_admin_user: DATestUser) -> None:
    basic: UserGroup = UserGroupManager.get_default(
        user_performing_action=new_admin_user, name="Basic"
    )
    member: DATestUser = UserManager.create(name="basic_pat_toggle_member")

    # On by default, so a fresh basic user mints a token.
    assert PAT_PERMISSION in UserGroupManager.get_permissions_by_id(
        basic.id, new_admin_user
    )
    minted: DATestPAT = PATManager.create(
        name="before-toggle", expiration_days=7, user_performing_action=member
    )
    assert minted.token is not None

    off: httpx.Response = UserGroupManager.set_permissions_by_id(
        basic.id, [], new_admin_user
    )
    off.raise_for_status()
    assert PAT_PERMISSION not in UserGroupManager.get_permissions_by_id(
        basic.id, new_admin_user
    )
    denied: httpx.Response = PATManager.create_response("after-toggle", 7, member)
    assert denied.status_code == 403

    on: httpx.Response = UserGroupManager.set_permissions_by_id(
        basic.id, [PAT_PERMISSION], new_admin_user
    )
    on.raise_for_status()
    restored: DATestPAT = PATManager.create(
        name="after-restore", expiration_days=7, user_performing_action=member
    )
    assert restored.token is not None

    # Only the allowlisted toggles exist on Basic, and Admin takes none.
    refused: httpx.Response = UserGroupManager.set_permissions_by_id(
        basic.id, [PAT_PERMISSION, Permission.MANAGE_LLMS.value], new_admin_user
    )
    assert refused.status_code == 409
    admin_group: UserGroup = UserGroupManager.get_default(
        user_performing_action=new_admin_user, name="Admin"
    )
    refused_on_admin: httpx.Response = UserGroupManager.set_permissions_by_id(
        admin_group.id, [PAT_PERMISSION], new_admin_user
    )
    assert refused_on_admin.status_code == 409
