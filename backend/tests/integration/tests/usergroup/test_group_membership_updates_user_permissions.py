import os

import pytest
from sqlalchemy import select
from sqlalchemy import update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import PermissionGrant
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup as UserGroupModel
from onyx.db.permissions import recompute_permissions_for_group__no_commit
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


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


def _is_group_manager(user_id: str) -> bool:
    with get_session_with_current_tenant() as db_session:
        value = db_session.scalar(
            select(User.is_group_manager).where(
                User.id == user_id  # ty: ignore[invalid-argument-type]
            )
        )
        assert value is not None
        return value


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

    # Verify the user gained the new permission (expanded includes read:agents)
    updated_permissions = UserManager.get_permissions(basic_user)
    assert "add:agents" in updated_permissions, (
        f"User should have 'add:agents' after group grant, got: {updated_permissions}"
    )
    assert "read:agents" in updated_permissions, (
        f"User should have implied 'read:agents', got: {updated_permissions}"
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

    assert _is_group_manager(member.id) is False

    _set_membership_is_manager(member.id, group.id, True)
    assert _is_group_manager(member.id) is True

    _set_membership_is_manager(member.id, group.id, False)
    assert _is_group_manager(member.id) is False


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
    assert _is_group_manager(member.id) is False

    _set_membership_is_manager(member.id, managed_group.id, True)
    assert _is_group_manager(member.id) is True

    _set_membership_is_manager(member.id, managed_group.id, False)
    assert _is_group_manager(member.id) is False
