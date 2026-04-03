import os

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import PermissionGrant
from onyx.db.models import UserGroup as UserGroupModel
from onyx.db.permissions import recompute_permissions_for_group__no_commit
from onyx.db.permissions import recompute_user_permissions__no_commit
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

    # Verify the user gained the new permission (expanded includes read:agents)
    updated_permissions = UserManager.get_permissions(basic_user)
    assert (
        "add:agents" in updated_permissions
    ), f"User should have 'add:agents' after group grant, got: {updated_permissions}"
    assert (
        "read:agents" in updated_permissions
    ), f"User should have implied 'read:agents', got: {updated_permissions}"
    assert "basic" in updated_permissions


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_group_permission_change_propagates_to_all_members(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_propagate")
    user_a: DATestUser = UserManager.create(name="user_a_propagate")
    user_b: DATestUser = UserManager.create(name="user_b_propagate")

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

    # Both users should now have the permission (plus implied read:agents)
    for u in (user_a, user_b):
        perms = UserManager.get_permissions(u)
        assert "add:agents" in perms, f"{u.id} missing add:agents: {perms}"
        assert "read:agents" in perms, f"{u.id} missing implied read:agents: {perms}"

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
