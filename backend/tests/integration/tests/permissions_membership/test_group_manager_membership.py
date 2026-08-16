"""Escalation suite for group-manager assignment + membership scoping.

A scoped group manager may create other managers, edit membership, rename, and
list groups — but only within the groups they manage. They can never assign a
manager, add users, rename, or edit a group outside their managed scope; never
attach a public or out-of-scope connector to their group; and never create,
delete, or set permissions on a group (all admin-only). The admin-facing group
list and ``/me/permissions`` return only the manager's own scope. Global holders
(admins) bypass GATE 2. Managers are seeded by flipping
``User__UserGroup.is_manager`` directly (no manager-creation helper exists yet).

Allowed actions go through the shared Manager classes (which assert real success);
denied actions go through the shared ``_access_matrix`` helpers, which verify the
403 is a genuine permission-gate denial rather than any incidental 403.
"""

import os
from typing import Any, NamedTuple

import pytest

from onyx.auth.permissions import SCOPED_MANAGER_PERMISSIONS_EXPANDED
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.models import User__UserGroup, UserGroup__ConnectorCredentialPair
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup
from tests.integration.tests.permissions._access_matrix import (
    assert_response,
    call_endpoint,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Group manager scoping is an enterprise-only capability",
)

_GROUP_LIST_PATH = "/manage/admin/user-group"
_RENAME_PATH = "/manage/admin/user-group/rename"
_ME_PERMISSIONS_PATH = "/me/permissions"
# Exactly what the Edit Group page's member picker requests.
_USERS_PATH = "/manage/users?include_api_keys=true"


class _ScopedEnv(NamedTuple):
    admin: DATestUser
    manager: DATestUser
    member: DATestUser  # plain member of managed_group (assignable target)
    outsider: DATestUser  # member of other_group only
    managed_group: DATestUserGroup
    other_group: DATestUserGroup


def _promote_to_manager(user_id: str, group_id: int) -> None:
    """Flip is_manager on the (user, group) edge and recompute the cached flag."""
    with get_session_with_current_tenant() as db_session:
        updated = (
            db_session.query(User__UserGroup)
            .filter(
                User__UserGroup.user_id == user_id,
                User__UserGroup.user_group_id == group_id,
            )
            .update({User__UserGroup.is_manager: True})
        )
        # A missing edge updates nothing and every test then runs against a plain member —
        # the denial cases would still pass, for the wrong reason.
        assert updated == 1, (
            f"no User__UserGroup edge for user {user_id} in group {group_id}"
        )
        db_session.flush()
        recompute_user_permissions__no_commit(user_id, db_session)
        db_session.commit()


@pytest.fixture
def env(reset: None, admin_user: DATestUser) -> _ScopedEnv:  # noqa: ARG001
    manager = UserManager.create(name="scoped_manager")
    member = UserManager.create(name="plain_member")
    outsider = UserManager.create(name="outsider")
    managed_group = UserGroupManager.create(
        name="managed",
        user_ids=[manager.id, member.id],
        user_performing_action=admin_user,
    )
    other_group = UserGroupManager.create(
        name="unmanaged", user_ids=[outsider.id], user_performing_action=admin_user
    )
    # Group creation kicks off a sync, and every edit route 409s/404s while one is in
    # flight — before GATE 2 runs, so an escalation test would "pass" without reaching it.
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[managed_group, other_group],
    )
    _promote_to_manager(manager.id, managed_group.id)
    return _ScopedEnv(admin_user, manager, member, outsider, managed_group, other_group)


def _manager_path(group_id: int) -> str:
    return f"/manage/admin/user-group/{group_id}/manager"


def _set_manager_body(user_id: str, is_manager: bool) -> dict[str, Any]:
    return {"user_id": user_id, "is_manager": is_manager}


def _me_permissions(user: DATestUser) -> dict[str, Any]:
    resp = client.get(
        url=f"{API_SERVER_URL}{_ME_PERMISSIONS_PATH}", headers=user.headers
    )
    resp.raise_for_status()
    return resp.json()


def _patch_group_body(user_ids: list[str], cc_pair_ids: list[int]) -> dict[str, Any]:
    return {"user_ids": user_ids, "cc_pair_ids": cc_pair_ids}


def _group_member_ids(group_id: int) -> set[str]:
    """Membership read from the DB — a status code only proves what came back."""
    with get_session_with_current_tenant() as db_session:
        return {
            str(row.user_id)
            for row in db_session.query(User__UserGroup).filter(
                User__UserGroup.user_group_id == group_id
            )
        }


def _current_cc_pair_ids(group_id: int) -> set[int]:
    """The group's live cc_pair junctions, read from the DB. A 403 only proves what came
    back; this proves the rejected write left no rows behind."""
    with get_session_with_current_tenant() as db_session:
        return {
            row.cc_pair_id
            for row in db_session.query(UserGroup__ConnectorCredentialPair).filter(
                UserGroup__ConnectorCredentialPair.user_group_id == group_id,
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
            )
        }


def _settled_cc_pair_ids(env: "_ScopedEnv") -> set[int]:
    """Wait out the sync a cc_pair create kicks off, then snapshot — same reason the
    ``env`` fixture waits."""
    UserGroupManager.wait_for_sync(
        user_performing_action=env.admin,
        user_groups_to_check=[env.managed_group, env.other_group],
    )
    return _current_cc_pair_ids(env.managed_group.id)


def _insert_stale_cc_pair_junction(group_id: int, cc_pair_id: int) -> None:
    """Simulate a removed-but-not-yet-swept cc_pair: an is_current=False junction row
    (removals mark the row stale rather than delete it, until the Vespa sync runs)."""
    with get_session_with_current_tenant() as db_session:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group_id, cc_pair_id=cc_pair_id, is_current=False
            )
        )
        db_session.commit()


# Manager-assignment endpoint — GATE 2 = admin or manager-of-that-group.
def test_admin_assigns_manager(env: _ScopedEnv) -> None:
    path = _manager_path(env.managed_group.id)
    resp = call_endpoint(
        "PUT",
        path,
        _set_manager_body(env.member.id, True),
        env.admin.headers,
        env.admin.cookies,
    )
    assert resp.status_code == 200, resp.text
    perms = _me_permissions(env.member)
    assert perms["is_manager"] is True
    assert env.managed_group.id in perms["managed_group_ids"]


def test_manager_delegates_within_managed_group(env: _ScopedEnv) -> None:
    # A manager may appoint a co-manager within a group they manage.
    path = _manager_path(env.managed_group.id)
    resp = call_endpoint(
        "PUT",
        path,
        _set_manager_body(env.member.id, True),
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text
    assert _me_permissions(env.member)["is_manager"] is True


def test_manager_cannot_assign_in_unmanaged_group(env: _ScopedEnv) -> None:
    path = _manager_path(env.other_group.id)
    resp = call_endpoint(
        "PUT",
        path,
        _set_manager_body(env.outsider.id, True),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_assign_non_member_returns_400(env: _ScopedEnv) -> None:
    # A manager is always a member — the outsider isn't in managed_group, so even
    # an admin gets a 400 (not a gate denial).
    path = _manager_path(env.managed_group.id)
    resp = call_endpoint(
        "PUT",
        path,
        _set_manager_body(env.outsider.id, True),
        env.admin.headers,
        env.admin.cookies,
    )
    assert resp.status_code == 400, resp.text


def test_revoke_manager_clears_flag(env: _ScopedEnv) -> None:
    manager_path = _manager_path(env.managed_group.id)
    call_endpoint(
        "PUT",
        manager_path,
        _set_manager_body(env.member.id, True),
        env.admin.headers,
        env.admin.cookies,
    )
    resp = call_endpoint(
        "PUT",
        manager_path,
        _set_manager_body(env.member.id, False),
        env.admin.headers,
        env.admin.cookies,
    )
    assert resp.status_code == 200, resp.text
    perms = _me_permissions(env.member)
    assert perms["is_manager"] is False
    assert env.managed_group.id not in perms["managed_group_ids"]


def test_plain_member_cannot_assign(env: _ScopedEnv) -> None:
    # A member without is_manager holds NONE for MANAGE_USER_GROUPS — GATE 1 rejects.
    path = _manager_path(env.managed_group.id)
    resp = call_endpoint(
        "PUT",
        path,
        _set_manager_body(env.member.id, True),
        env.member.headers,
        env.member.cookies,
    )
    assert_response(resp, "PUT", path, "member", "denied")


def test_manager_adds_user_to_managed_group(env: _ScopedEnv) -> None:
    UserGroupManager.add_users(
        env.managed_group, [env.outsider.id], user_performing_action=env.manager
    )


def test_manager_cannot_add_user_to_unmanaged_group(env: _ScopedEnv) -> None:
    path = f"/manage/admin/user-group/{env.other_group.id}/add-users"
    resp = call_endpoint(
        "POST",
        path,
        {"user_ids": [env.member.id]},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "POST", path, "manager", "denied")


def test_manager_cannot_remove_self_from_managed_group(env: _ScopedEnv) -> None:
    """is_manager lives on the membership edge, so dropping yourself is a one-way
    lockout. The member list disables it; the route has to reject it too."""
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.member.id], []),
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 400, resp.text
    assert _group_member_ids(env.managed_group.id) >= {env.manager.id, env.member.id}


def test_global_holder_cannot_remove_self_from_their_granting_group(
    env: _ScopedEnv,
) -> None:
    """effective_permissions is derived from group grants, so leaving can revoke the very
    authority that admitted the caller. The exemption has to be judged against the state
    after the removal, not before it."""
    holder = UserManager.create(name="grant_holder")
    group = UserGroupManager.create(
        name="grant-source",
        user_ids=[holder.id],
        cc_pair_ids=[],
        user_performing_action=env.admin,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=env.admin, user_groups_to_check=[group]
    )
    UserGroupManager.set_permissions(
        group, ["manage:user_groups"], env.admin
    ).raise_for_status()

    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{group.id}",
        _patch_group_body([], []),
        holder.headers,
        holder.cookies,
    )
    assert resp.status_code == 400, resp.text
    assert holder.id in _group_member_ids(group.id)


def test_admin_may_remove_self_from_group(env: _ScopedEnv) -> None:
    """A global holder whose grant comes from elsewhere keeps authority regardless of
    this membership, so there is no lockout to prevent — the guard must not catch them."""
    UserGroupManager.add_users(
        env.managed_group, [env.admin.id], user_performing_action=env.admin
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=env.admin, user_groups_to_check=[env.managed_group]
    )
    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{env.managed_group.id}",
        _patch_group_body([env.manager.id, env.member.id], []),
        env.admin.headers,
        env.admin.cookies,
    )
    assert resp.status_code == 200, resp.text
    assert env.admin.id not in _group_member_ids(env.managed_group.id)


def test_manager_renames_managed_group(env: _ScopedEnv) -> None:
    resp = call_endpoint(
        "PATCH",
        _RENAME_PATH,
        {"id": env.managed_group.id, "name": "managed-renamed"},
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text


def test_manager_cannot_rename_unmanaged_group(env: _ScopedEnv) -> None:
    resp = call_endpoint(
        "PATCH",
        _RENAME_PATH,
        {"id": env.other_group.id, "name": "unmanaged-renamed"},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", _RENAME_PATH, "manager", "denied")


def test_manager_cannot_patch_unmanaged_group(env: _ScopedEnv) -> None:
    path = f"/manage/admin/user-group/{env.other_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.outsider.id], []),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")


# cc_pair re-attach gate — the junction-rewrite escalation vector.
def test_manager_cannot_attach_public_cc_pair(env: _ScopedEnv) -> None:
    public_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=AccessType.PUBLIC, groups=[]
    )
    before = _settled_cc_pair_ids(env)
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.manager.id, env.member.id], [public_cc_pair.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")
    assert _current_cc_pair_ids(env.managed_group.id) == before
    assert public_cc_pair.id not in before


def test_manager_cannot_attach_unmanaged_cc_pair(env: _ScopedEnv) -> None:
    # Admin owns a PRIVATE cc_pair in a group the manager does not manage.
    unmanaged_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.other_group.id],
    )
    before = _settled_cc_pair_ids(env)
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.manager.id, env.member.id], [unmanaged_cc_pair.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")
    assert _current_cc_pair_ids(env.managed_group.id) == before
    assert unmanaged_cc_pair.id not in before


def test_manager_cannot_reattach_removed_public_cc_pair(env: _ScopedEnv) -> None:
    # A removed cc_pair leaves a stale is_current=False junction row until the sync
    # sweeps it; that stale row must not make a public connector look "already
    # attached" and slip past the re-attach gate.
    public_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=AccessType.PUBLIC, groups=[]
    )
    before = _settled_cc_pair_ids(env)
    _insert_stale_cc_pair_junction(env.managed_group.id, public_cc_pair.id)
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.manager.id, env.member.id], [public_cc_pair.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")
    # The stale row must stay stale — revival is the escalation this test guards.
    assert _current_cc_pair_ids(env.managed_group.id) == before
    assert public_cc_pair.id not in before


def test_manager_attaches_groupless_private_cc_pair(env: _ScopedEnv) -> None:
    # A private cc_pair in no group lands only in managed scope when attached —
    # so the manager may pull it into their group.
    groupless_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=AccessType.PRIVATE, groups=[]
    )
    _settled_cc_pair_ids(env)
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _patch_group_body([env.manager.id, env.member.id], [groupless_cc_pair.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text
    assert groupless_cc_pair.id in _current_cc_pair_ids(env.managed_group.id)


def test_manager_group_list_only_managed(env: _ScopedEnv) -> None:
    groups = UserGroupManager.get_all(user_performing_action=env.manager)
    group_ids = {g.id for g in groups}
    assert env.managed_group.id in group_ids
    assert env.other_group.id not in group_ids


def test_admin_group_list_includes_all(env: _ScopedEnv) -> None:
    groups = UserGroupManager.get_all(user_performing_action=env.admin)
    group_ids = {g.id for g in groups}
    assert {env.managed_group.id, env.other_group.id}.issubset(group_ids)


def test_manager_reads_member_candidates(env: _ScopedEnv) -> None:
    """The roster behind the Edit Group member picker. MANAGE_USER_GROUPS implies
    READ_USERS, so a manager resolves it SCOPED — the route must allow_scope or this
    403s and the page renders "Failed to load group data", blaming the group fetch
    that actually succeeded. Not narrowed to the managed group: picking a new member
    means seeing users who aren't in it yet.
    """
    resp = call_endpoint(
        "GET", _USERS_PATH, None, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "GET", _USERS_PATH, "manager", "allowed")
    emails = {u["email"] for u in resp.json()["accepted"]}
    assert {env.manager.email, env.outsider.email}.issubset(emails)


def test_plain_member_cannot_read_candidates(env: _ScopedEnv) -> None:
    resp = call_endpoint(
        "GET", _USERS_PATH, None, env.member.headers, env.member.cookies
    )
    assert_response(resp, "GET", _USERS_PATH, "member", "denied")


def test_manager_me_permissions_flags(env: _ScopedEnv) -> None:
    perms = _me_permissions(env.manager)
    assert perms["is_manager"] is True
    # Exact set, not just contains: a leaked managed group (e.g. a stray is_manager edge on
    # the org-wide default group) would broaden real GATE-2 scope, so pin it precisely.
    assert perms["managed_group_ids"] == [env.managed_group.id]

    info = UserManager.get_user_info(env.manager)
    effective = set(info.effective_permissions)
    assert info.is_group_manager is True
    # admin_capabilities unions the scoped bundle so the client can reveal manager nav
    assert (
        set(info.admin_capabilities) == effective | SCOPED_MANAGER_PERMISSIONS_EXPANDED
    )
    assert set(info.admin_capabilities) > effective


def test_member_me_permissions_not_manager(env: _ScopedEnv) -> None:
    perms = _me_permissions(env.member)
    assert perms["is_manager"] is False
    assert perms["managed_group_ids"] == []

    info = UserManager.get_user_info(env.member)
    assert info.is_group_manager is False
    assert set(info.admin_capabilities) == set(info.effective_permissions)


# Group create/delete/set-permissions stay admin-only.
def test_manager_cannot_create_group(env: _ScopedEnv) -> None:
    resp = call_endpoint(
        "POST",
        _GROUP_LIST_PATH,
        {"name": "new-group", "user_ids": [], "cc_pair_ids": []},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "POST", _GROUP_LIST_PATH, "manager", "denied")


def test_manager_cannot_delete_group(env: _ScopedEnv) -> None:
    path = f"/manage/admin/user-group/{env.managed_group.id}"
    resp = call_endpoint("DELETE", path, None, env.manager.headers, env.manager.cookies)
    assert_response(resp, "DELETE", path, "manager", "denied")


def test_manager_cannot_set_group_permissions(env: _ScopedEnv) -> None:
    path = f"/manage/admin/user-group/{env.managed_group.id}/permissions"
    resp = call_endpoint(
        "PUT",
        path,
        {"permissions": []},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")
