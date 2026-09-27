import os

import httpx
import pytest
from sqlalchemy import update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import PermissionGrant, User__UserGroup
from onyx.db.models import UserGroup as UserGroupModel
from onyx.db.permissions import (
    recompute_permissions_for_group__no_commit,
    recompute_user_permissions__no_commit,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.permission_state import is_group_manager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup


def _set_membership_is_manager(user_id: str, group_id: int, value: bool) -> None:
    """Flip is_manager on one (user, group) edge, then recompute.

    make_group_manager lands in a later PR, so promote by writing the edge directly.
    """
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == user_id,
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=value)
        )
        db_session.flush()
        recompute_user_permissions__no_commit(user_id, db_session)
        db_session.commit()


def _set_members(
    group_id: int, user_ids: list[str], admin_user: DATestUser
) -> httpx.Response:
    return client.patch(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_id}",
        json={"user_ids": user_ids, "cc_pair_ids": []},
        headers=admin_user.headers,
    )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_user_gets_permissions_when_added_to_group(admin_user: DATestUser) -> None:
    basic_user: DATestUser = UserManager.create()

    # basic_user starts with only "basic" from the default group
    initial_permissions = UserManager.get_permissions(basic_user)
    assert "basic" in initial_permissions
    assert "add:agents" not in initial_permissions

    # Create a new group and add basic_user
    group = UserGroupManager.create(
        name="perm-test-group",
        user_ids=[admin_user.id, basic_user.id],
        user_performing_action=admin_user,
    )

    # Grant a non-basic permission to the group and recompute
    with get_session_with_current_tenant() as db_session:
        db_group = db_session.get(UserGroupModel, group.id)
        assert db_group is not None
        db_session.add(
            PermissionGrant(
                group_id=db_group.id,
                permission=Permission.ADD_AGENTS,
                grant_source="SYSTEM",
            )
        )
        db_session.flush()
        recompute_user_permissions__no_commit(basic_user.id, db_session)
        db_session.commit()

    updated_permissions = UserManager.get_permissions(basic_user)
    assert "add:agents" in updated_permissions, (
        f"User should have 'add:agents' after group grant, got: {updated_permissions}"
    )
    # add:agents must not imply read:agents — making your own agents is not see-all
    assert "read:agents" not in updated_permissions, (
        f"'add:agents' must not grant see-all visibility, got: {updated_permissions}"
    )
    assert "basic" in updated_permissions


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_group_permission_change_propagates_to_all_members(
    admin_user: DATestUser,
) -> None:
    user_a: DATestUser = UserManager.create()
    user_b: DATestUser = UserManager.create()

    group = UserGroupManager.create(
        name="propagate-test-group",
        user_ids=[admin_user.id, user_a.id, user_b.id],
        user_performing_action=admin_user,
    )

    # Neither user should have add:agents yet
    for u in (user_a, user_b):
        assert "add:agents" not in UserManager.get_permissions(u)

    # Grant add:agents to the group, then batch-recompute
    with get_session_with_current_tenant() as db_session:
        grant = PermissionGrant(
            group_id=group.id,
            permission=Permission.ADD_AGENTS,
            grant_source="SYSTEM",
        )
        db_session.add(grant)
        db_session.flush()
        recompute_permissions_for_group__no_commit(group.id, db_session)
        db_session.commit()

    # add:agents must not imply read:agents — making your own agents is not see-all
    for u in (user_a, user_b):
        perms = UserManager.get_permissions(u)
        assert "add:agents" in perms, f"{u.id} missing add:agents: {perms}"
        assert "read:agents" not in perms, f"{u.id} must not gain see-all: {perms}"

    # Soft-delete the grant and recompute — permission should be removed
    with get_session_with_current_tenant() as db_session:
        db_grant = (
            db_session.query(PermissionGrant)
            .filter_by(group_id=group.id, permission=Permission.ADD_AGENTS)
            .first()
        )
        assert db_grant is not None
        db_grant.is_deleted = True
        db_session.flush()
        recompute_permissions_for_group__no_commit(group.id, db_session)
        db_session.commit()

    for u in (user_a, user_b):
        perms = UserManager.get_permissions(u)
        assert "add:agents" not in perms, f"{u.id} still has add:agents: {perms}"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_is_group_manager_flag_recomputed_on_manager_change(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """is_group_manager is the second column recompute writes (with effective_permissions)."""
    member: DATestUser = UserManager.create()
    group = UserGroupManager.create(
        name="manager-flag-group",
        user_ids=[admin_user.id, member.id],
        user_performing_action=admin_user,
    )

    assert is_group_manager(member.id) is False

    _set_membership_is_manager(member.id, group.id, True)
    assert is_group_manager(member.id) is True

    _set_membership_is_manager(member.id, group.id, False)
    assert is_group_manager(member.id) is False


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_is_group_manager_true_when_managing_any_group(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Managing one group is enough — even while a plain member of another."""
    member: DATestUser = UserManager.create()
    UserGroupManager.create(
        name="plain-member-group",
        user_ids=[admin_user.id, member.id],
        user_performing_action=admin_user,
    )
    managed_group = UserGroupManager.create(
        name="managed-group",
        user_ids=[admin_user.id, member.id],
        user_performing_action=admin_user,
    )
    assert is_group_manager(member.id) is False

    _set_membership_is_manager(member.id, managed_group.id, True)
    assert is_group_manager(member.id) is True

    _set_membership_is_manager(member.id, managed_group.id, False)
    assert is_group_manager(member.id) is False


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_removing_a_users_last_group_is_rejected(admin_user: DATestUser) -> None:
    """A new user starts in Basic, so that membership has to go first."""
    member: DATestUser = UserManager.create()
    group: DATestUserGroup = UserGroupManager.create(
        name="last-group",
        user_ids=[member.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )

    basic = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    response = _set_members(
        basic.id,
        [other.id for other in basic.users if other.id != member.id],
        admin_user,
    )
    assert response.status_code == 200, response.text

    # the new group is now their only one
    response = _set_members(group.id, [], admin_user)
    assert response.status_code == 400, response.text
    assert member.email in response.text

    still_a_member = next(
        fetched
        for fetched in UserGroupManager.get_all(user_performing_action=admin_user)
        if fetched.id == group.id
    ).users
    assert member.id in {user.id for user in still_a_member}


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_removal_allowed_while_another_group_survives(admin_user: DATestUser) -> None:
    member: DATestUser = UserManager.create()
    group: DATestUserGroup = UserGroupManager.create(
        name="two-groups",
        user_ids=[member.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )

    # basic still holds the member, so this group can let them go
    response = _set_members(group.id, [], admin_user)
    assert response.status_code == 200, response.text


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_deleting_a_users_last_group_is_rejected(admin_user: DATestUser) -> None:
    """Deletion drops every membership at once, so it answers to the same rule."""
    member: DATestUser = UserManager.create()
    group: DATestUserGroup = UserGroupManager.create(
        name="last-group-delete",
        user_ids=[member.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )

    basic = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    response = _set_members(
        basic.id,
        [other.id for other in basic.users if other.id != member.id],
        admin_user,
    )
    assert response.status_code == 200, response.text

    response = client.delete(
        f"{API_SERVER_URL}/manage/admin/user-group/{group.id}",
        headers=admin_user.headers,
    )
    assert response.status_code == 400, response.text
    assert member.email in response.text

    assert group.id in {
        fetched.id
        for fetched in UserGroupManager.get_all(user_performing_action=admin_user)
    }
