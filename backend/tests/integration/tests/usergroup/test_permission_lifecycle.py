"""Revocation-direction tests for group-derived permissions.

The suite asserted that permissions arrive, never that they leave, so membership
removal, group deletion, grant revocation and manager-flag depopulation were all
uncovered.

Assertions use ``/me/permissions`` plus a real gated route rather than the
``effective_permissions`` column: that column is read with a raw JSONB
``contains`` in a few places, so a stale value there bypasses every gate.
"""

import os

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.permission_state import (
    is_group_manager,
    managed_group_ids,
)
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permissions are enterprise only",
)

# A GET gated on manage:llms — proves the grant reaches a route, not just /me.
_LLM_ROUTE = "/admin/llm/provider"


def _can_reach_llm_admin(user: DATestUser) -> bool:
    resp = client.get(
        f"{API_SERVER_URL}{_LLM_ROUTE}", headers=user.headers, cookies=user.cookies
    )
    assert resp.status_code in (200, 403), resp.text
    return resp.status_code == 200


def _grant_group(
    admin: DATestUser, name: str, members: list[str], permission: Permission
) -> DATestUserGroup:
    group = UserGroupManager.create(
        name=name,
        user_ids=members,
        cc_pair_ids=[],
        user_performing_action=admin,
    )
    # Creation kicks off a sync, and edit/delete routes reject the group while one is
    # in flight — a later delete 404s without this.
    UserGroupManager.wait_for_sync(
        user_performing_action=admin, user_groups_to_check=[group]
    )
    UserGroupManager.set_permissions(
        user_group=group,
        permissions=[permission.value],
        user_performing_action=admin,
    ).raise_for_status()
    return group


def _remove_members(admin: DATestUser, group: DATestUserGroup, keep: list[str]) -> None:
    group.user_ids = keep
    UserGroupManager.edit(user_group=group, user_performing_action=admin)


def test_removing_user_from_group_revokes_its_permissions(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    member = UserManager.create(name="revoke_member")
    group = _grant_group(admin_user, "revoke-llms", [member.id], Permission.MANAGE_LLMS)

    assert "manage:llms" in UserManager.get_permissions(member)
    assert _can_reach_llm_admin(member)

    _remove_members(admin_user, group, keep=[])

    permissions = UserManager.get_permissions(member)
    assert "manage:llms" not in permissions
    assert not _can_reach_llm_admin(member)
    # basic comes from the default group, so revocation must not be a blanket wipe
    assert "basic" in permissions


def test_group_deletion_revokes_its_permissions(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    member = UserManager.create(name="delete_member")
    group = _grant_group(admin_user, "delete-llms", [member.id], Permission.MANAGE_LLMS)
    assert "manage:llms" in UserManager.get_permissions(member)

    UserGroupManager.delete(user_group=group, user_performing_action=admin_user)

    permissions = UserManager.get_permissions(member)
    assert "manage:llms" not in permissions
    assert "basic" in permissions


def test_revoked_permission_can_be_regranted(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Revocation soft-deletes the grant and re-granting reactivates it. The
    unique constraint on (group_id, permission) has no is_deleted predicate, so a
    re-grant that inserted instead of reactivating would 500 here."""
    member = UserManager.create(name="regrant_member")
    group = _grant_group(
        admin_user, "regrant-llms", [member.id], Permission.MANAGE_LLMS
    )
    assert "manage:llms" in UserManager.get_permissions(member)

    UserGroupManager.set_permissions(
        user_group=group, permissions=[], user_performing_action=admin_user
    ).raise_for_status()
    assert "manage:llms" not in UserManager.get_permissions(member)

    UserGroupManager.set_permissions(
        user_group=group,
        permissions=[Permission.MANAGE_LLMS.value],
        user_performing_action=admin_user,
    ).raise_for_status()

    assert "manage:llms" in UserManager.get_permissions(member)
    assert _can_reach_llm_admin(member)


def test_leaving_one_group_keeps_the_others_permissions(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Permissions union over groups. Every other revocation test is
    single-source, so only this one tells a correct revoke from a column wipe."""
    member = UserManager.create(name="multi_group_member")
    llm_group = _grant_group(
        admin_user, "multi-llms", [member.id], Permission.MANAGE_LLMS
    )
    _grant_group(admin_user, "multi-bots", [member.id], Permission.MANAGE_BOTS)

    permissions = UserManager.get_permissions(member)
    assert {"manage:llms", "manage:bots"} <= set(permissions)

    _remove_members(admin_user, llm_group, keep=[])

    permissions = UserManager.get_permissions(member)
    assert "manage:llms" not in permissions
    assert "manage:bots" in permissions
    assert "basic" in permissions


def test_removing_a_manager_from_their_group_clears_the_flag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    manager = UserManager.create(name="depop_manager")
    group = _grant_group(
        admin_user, "depop-membership", [manager.id], Permission.MANAGE_LLMS
    )
    UserGroupManager.set_manager(
        user_group=group,
        user=manager,
        is_manager=True,
        user_performing_action=admin_user,
    ).raise_for_status()
    assert is_group_manager(manager.id)

    _remove_members(admin_user, group, keep=[])

    # The edge carries is_manager, so losing membership must lose the role.
    assert managed_group_ids(manager.id) == set()
    assert not is_group_manager(manager.id)


def test_deleting_a_managed_group_clears_the_flag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    manager = UserManager.create(name="depop_group_manager")
    group = _grant_group(
        admin_user, "depop-deletion", [manager.id], Permission.MANAGE_LLMS
    )
    UserGroupManager.set_manager(
        user_group=group,
        user=manager,
        is_manager=True,
        user_performing_action=admin_user,
    ).raise_for_status()
    assert is_group_manager(manager.id)

    UserGroupManager.delete(user_group=group, user_performing_action=admin_user)

    assert managed_group_ids(manager.id) == set()
    assert not is_group_manager(manager.id)


def test_manager_of_two_groups_survives_losing_one(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """is_group_manager is an ANY rollup. Recomputing it against only the changed
    group — the obvious optimisation, since every call site knows which one changed
    — would strand this user at False and lock them out at GATE 1, where the live
    scope lookup never runs to correct it."""
    manager = UserManager.create(name="two_group_manager")
    first = _grant_group(
        admin_user, "two-group-a", [manager.id], Permission.MANAGE_LLMS
    )
    second = _grant_group(
        admin_user, "two-group-b", [manager.id], Permission.MANAGE_BOTS
    )
    for group in (first, second):
        UserGroupManager.set_manager(
            user_group=group,
            user=manager,
            is_manager=True,
            user_performing_action=admin_user,
        ).raise_for_status()
    assert managed_group_ids(manager.id) == {first.id, second.id}

    _remove_members(admin_user, first, keep=[])

    assert managed_group_ids(manager.id) == {second.id}
    assert is_group_manager(manager.id)
