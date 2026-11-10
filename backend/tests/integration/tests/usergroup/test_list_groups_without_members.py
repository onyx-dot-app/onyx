import os

import pytest

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_list_groups_without_members_sends_counts(admin_user: DATestUser) -> None:
    active_member = UserManager.create()
    inactive_member = UserManager.create()
    user_group = UserGroupManager.create(
        name="list-without-members",
        user_ids=[admin_user.id, active_member.id, inactive_member.id],
        user_performing_action=admin_user,
    )
    empty_group = UserGroupManager.create(
        name="list-without-members-empty",
        user_performing_action=admin_user,
    )
    UserManager.set_status(
        user_to_set=inactive_member,
        target_status=False,
        user_performing_action=admin_user,
    )

    full = {
        group.id: group
        for group in UserGroupManager.get_all(user_performing_action=admin_user)
    }
    summaries = {
        group.id: group
        for group in UserGroupManager.get_all(
            user_performing_action=admin_user, include_users=False
        )
    }

    assert full.keys() == summaries.keys()

    full_group = full[user_group.id]
    assert len(full_group.users) == 3
    assert full_group.member_count == 3
    assert full_group.active_member_count == 2

    summary = summaries[user_group.id]
    assert summary.users == []
    assert summary.member_count == 3
    assert summary.active_member_count == 2
    assert summary.manager_ids == full_group.manager_ids

    empty_summary = summaries[empty_group.id]
    assert empty_summary.member_count == 0
    assert empty_summary.active_member_count == 0
