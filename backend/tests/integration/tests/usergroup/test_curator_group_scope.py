"""
Regression tests for a curator group-scope privilege-escalation bug.

A user with the CURATOR role could modify *any* user group (not just the ones
they curate) via:

    PATCH /manage/admin/user-group/{user_group_id}
    POST  /manage/admin/user-group/{user_group_id}/add-users

Both routes guard with ``current_curator_or_admin_user`` (which only proves the
caller is a curator/admin *somewhere*) while the underlying DB functions ignored
the caller entirely. This let a curator of Group A rewrite the membership /
cc_pair assignments of Group B (e.g. add themselves to a sensitive group).

These tests verify the caller is now scoped: a CURATOR to the groups they
actually curate, and a GLOBAL_CURATOR to the groups they are a member of.
"""

import os

import pytest

from onyx.db.models import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import DATestUser
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_curator_cannot_modify_unscoped_group(reset: None) -> None:  # noqa: ARG001
    # First user created is automatically an admin
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    curator: DATestUser = UserManager.create(name="curator")
    other_user: DATestUser = UserManager.create(name="other_user")

    # Group A: the curator is a member and will be made its curator.
    group_a = UserGroupManager.create(
        name="group_a",
        user_ids=[curator.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    # Group B: the curator has no relationship to this group.
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

    UserGroupManager.set_curator_status(
        test_user_group=group_a,
        user_to_set_as_curator=curator,
        user_performing_action=admin_user,
    )
    assert UserManager.is_role(curator, UserRole.CURATOR)

    # --- Negative: curator cannot PATCH a group they don't curate ---
    patch_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}",
        json={"user_ids": [curator.id], "cc_pair_ids": []},
        headers=curator.headers,
    )
    assert patch_resp.status_code == 403

    # --- Negative: curator cannot add users to a group they don't curate ---
    add_resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}/add-users",
        json={"user_ids": [curator.id]},
        headers=curator.headers,
    )
    assert add_resp.status_code == 403

    # The curator must not have been added to group B as a side effect.
    admin_view = UserGroupManager.get_all(user_performing_action=admin_user)
    group_b_view = next(group for group in admin_view if group.id == group_b.id)
    assert curator.id not in {str(user.id) for user in group_b_view.users}

    # --- Positive: curator can still PATCH the group they curate ---
    patch_own_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_a.id}",
        json={"user_ids": [curator.id], "cc_pair_ids": []},
        headers=curator.headers,
    )
    assert patch_own_resp.status_code == 200

    # --- Positive: curator can still add users to the group they curate ---
    UserGroupManager.add_users(
        user_group=group_a,
        user_ids=[other_user.id],
        user_performing_action=curator,
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
def test_global_curator_scoped_to_member_groups(reset: None) -> None:  # noqa: ARG001
    """A GLOBAL_CURATOR may modify groups they are a member of, but not others.

    This mirrors the documented role semantics (``UserRole``) and the existing
    ``validate_object_creation_for_user`` scoping: "global curators can curate
    all groups they are a member of" -- not every group in the deployment.
    """
    # First user created is automatically an admin
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    global_curator: DATestUser = UserManager.create(name="global_curator")
    other_user: DATestUser = UserManager.create(name="other_user")

    UserManager.set_role(
        user_to_set=global_curator,
        target_role=UserRole.GLOBAL_CURATOR,
        user_performing_action=admin_user,
    )
    assert UserManager.is_role(global_curator, UserRole.GLOBAL_CURATOR)

    # Group A: the global curator is a member.
    group_a = UserGroupManager.create(
        name="group_a",
        user_ids=[global_curator.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    # Group B: the global curator is not a member.
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

    # --- Negative: cannot PATCH a group they are not a member of ---
    patch_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}",
        json={"user_ids": [global_curator.id], "cc_pair_ids": []},
        headers=global_curator.headers,
    )
    assert patch_resp.status_code == 403

    # --- Negative: cannot add users to a group they are not a member of ---
    add_resp = client.post(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_b.id}/add-users",
        json={"user_ids": [global_curator.id]},
        headers=global_curator.headers,
    )
    assert add_resp.status_code == 403

    # The global curator must not have been added to group B as a side effect.
    admin_view = UserGroupManager.get_all(user_performing_action=admin_user)
    group_b_view = next(group for group in admin_view if group.id == group_b.id)
    assert global_curator.id not in {str(user.id) for user in group_b_view.users}

    # --- Positive: can still modify a group they are a member of ---
    patch_own_resp = client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_a.id}",
        json={"user_ids": [global_curator.id], "cc_pair_ids": []},
        headers=global_curator.headers,
    )
    assert patch_own_resp.status_code == 200

    UserGroupManager.add_users(
        user_group=group_a,
        user_ids=[other_user.id],
        user_performing_action=global_curator,
    )
    # Re-fetch rather than trust the add-users response body, which does not
    # reflect the freshly inserted membership.
    member_view = UserGroupManager.get_all(user_performing_action=admin_user)
    group_a_view = next(group for group in member_view if group.id == group_a.id)
    assert other_user.id in {str(user.id) for user in group_a_view.users}
