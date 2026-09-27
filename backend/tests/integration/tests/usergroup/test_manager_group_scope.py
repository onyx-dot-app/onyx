"""
Regression test for a group-scope privilege-escalation bug.

A user who managed *some* group could modify *any* user group via:

    PATCH /manage/admin/user-group/{user_group_id}
    POST  /manage/admin/user-group/{user_group_id}/add-users

GATE 1 (``require_permission(MANAGE_USER_GROUPS, allow_scope=True)``) only
proves the caller manages something somewhere; without GATE 2 the underlying DB
functions ignored the caller entirely. That let the manager of Group A rewrite
the membership / cc_pair assignments of Group B (e.g. add themselves to a
sensitive group).

This verifies GATE 2 scopes the caller to the groups they actually manage.

Note there is deliberately no "member of the group" variant: under the
permission system, plain membership grants no management rights at all — only
the per-group ``is_manager`` edge does.
"""

import os

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import DATestUser, UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_manager_cannot_modify_unscoped_group(reset: None) -> None:  # noqa: ARG001
    # First user created is automatically an admin
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert UserManager.is_admin(admin_user)

    manager: DATestUser = UserManager.create(name="manager")
    other_user: DATestUser = UserManager.create(name="other_user")

    # Group A: the manager is a member and will be made its manager.
    group_a = UserGroupManager.create(
        name="group_a",
        user_ids=[manager.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    # Group B: the manager has no relationship to this group.
    group_b = UserGroupManager.create(
        name="group_b",
        user_ids=[],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[group_a, group_b],
        user_performing_action=admin_user,
    )

    set_manager_resp = UserGroupManager.set_manager(
        user_group=group_a,
        user=manager,
        is_manager=True,
        user_performing_action=admin_user,
    )
    assert set_manager_resp.status_code == 200

    # --- Negative: manager cannot PATCH a group they don't manage ---
    patch_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}",
        json={"user_ids": [manager.id], "cc_pair_ids": []},
        headers=manager.headers,
    )
    assert patch_resp.status_code == 403

    # --- Negative: manager cannot add users to a group they don't manage ---
    add_resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}/add-users",
        json={"user_ids": [manager.id]},
        headers=manager.headers,
    )
    assert add_resp.status_code == 403

    # The manager must not have been added to group B as a side effect.
    admin_view = UserGroupManager.get_all(user_performing_action=admin_user)
    group_b_view = next(group for group in admin_view if group.id == group_b.id)
    assert manager.id not in {str(user.id) for user in group_b_view.users}

    # --- Positive: manager can still PATCH the group they manage ---
    patch_own_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_a.id}",
        json={"user_ids": [manager.id], "cc_pair_ids": []},
        headers=manager.headers,
    )
    assert patch_own_resp.status_code == 200

    # --- Positive: manager can still add users to the group they manage ---
    UserGroupManager.add_users(
        user_group=group_a,
        user_ids=[other_user.id],
        user_performing_action=manager,
    )
    # Re-fetch rather than trust the add-users response body, which does not
    # reflect the freshly inserted membership.
    admin_view = UserGroupManager.get_all(user_performing_action=admin_user)
    group_a_view = next(group for group in admin_view if group.id == group_a.id)
    assert other_user.id in {str(user.id) for user in group_a_view.users}

    # --- Admin is unaffected: can modify any group ---
    admin_add_resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}/add-users",
        json={"user_ids": [other_user.id]},
        headers=admin_user.headers,
    )
    assert admin_add_resp.status_code == 200


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_plain_member_cannot_modify_their_group(reset: None) -> None:  # noqa: ARG001
    """Membership is not management: without the is_manager edge, a member of a
    group still cannot modify it. This is the case the old GLOBAL_CURATOR role
    allowed and the permission system deliberately does not."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert UserManager.is_admin(admin_user)

    member: DATestUser = UserManager.create(name="member")

    group = UserGroupManager.create(
        name="group_a",
        user_ids=[member.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[group],
        user_performing_action=admin_user,
    )

    patch_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group.id}",
        json={"user_ids": [member.id], "cc_pair_ids": []},
        headers=member.headers,
    )
    assert patch_resp.status_code == 403

    add_resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{group.id}/add-users",
        json={"user_ids": [member.id]},
        headers=member.headers,
    )
    assert add_resp.status_code == 403
