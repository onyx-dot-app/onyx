"""Editor and Operator manage roles on connectors.

Operators run a connector (pause, rename, schedule, index, prune). Editors also
change and delete it and decide who manages it. A group manager holds the role of
the groups they manage, for every access type. Global MANAGE_CONNECTORS holders are
Editors of every connector, and their groups show as fixed rows.
"""

import os
from collections.abc import Callable
from typing import Any, NamedTuple
from uuid import uuid4

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorManageRole
from onyx.server.documents.models import ConnectorUpdateRequest
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import (
    DATestCCPair,
    DATestUser,
    DATestUserGroup,
)
from tests.integration.tests.permissions._access_matrix import call_endpoint

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="Manage roles need user groups, an enterprise-only capability",
)


class _RolesEnv(NamedTuple):
    admin: DATestUser
    editor: DATestUser
    operator: DATestUser
    no_role: DATestUser
    editor_group: DATestUserGroup
    operator_group: DATestUserGroup
    no_role_group: DATestUserGroup


def _manager_of(name: str, admin: DATestUser) -> tuple[DATestUser, DATestUserGroup]:
    user = UserManager.create(name=f"{name}-{uuid4().hex[:8]}")
    group = UserGroupManager.create(
        name=f"{name}-group-{uuid4().hex[:8]}",
        user_ids=[user.id],
        user_performing_action=admin,
    )
    UserGroupManager.set_manager(
        user_group=group, user=user, is_manager=True, user_performing_action=admin
    ).raise_for_status()
    return user, group


@pytest.fixture(scope="module")
def env(permission_admin_user: DATestUser) -> _RolesEnv:
    editor, editor_group = _manager_of("roles-editor", permission_admin_user)
    operator, operator_group = _manager_of("roles-operator", permission_admin_user)
    no_role, no_role_group = _manager_of("roles-norole", permission_admin_user)
    return _RolesEnv(
        permission_admin_user,
        editor,
        operator,
        no_role,
        editor_group,
        operator_group,
        no_role_group,
    )


def _pair(env: _RolesEnv, access_type: AccessType) -> DATestCCPair:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=access_type, groups=[]
    )
    CCPairManager.set_manage_access(
        cc_pair.id,
        {
            env.editor_group.id: ConnectorManageRole.EDITOR,
            env.operator_group.id: ConnectorManageRole.OPERATOR,
        },
        user_performing_action=env.admin,
    )
    return cc_pair


def _call(
    user: DATestUser, method: str, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    return call_endpoint(method, path, body, user.headers, user.cookies)


def _connector_body(cc_pair: DATestCCPair) -> dict[str, Any]:
    return ConnectorUpdateRequest(
        name=f"renamed-{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata_file_id": None,
        },
        access_type=cc_pair.access_type,
        groups=[],
    ).model_dump(mode="json")


_Action = Callable[[DATestUser, DATestCCPair], httpx.Response]

_OPERATOR_ACTIONS: dict[str, _Action] = {
    "pause": lambda user, pair: _call(
        user, "PUT", f"/manage/admin/cc-pair/{pair.id}/status", {"status": "PAUSED"}
    ),
    "rename": lambda user, pair: _call(
        user, "PUT", f"/manage/admin/cc-pair/{pair.id}/name?new_name=r-{uuid4()}"
    ),
    "refresh_frequency": lambda user, pair: _call(
        user,
        "PUT",
        f"/manage/admin/cc-pair/{pair.id}/property",
        {"name": "refresh_frequency", "value": "3600"},
    ),
    "run_once": lambda user, pair: _call(
        user,
        "POST",
        "/manage/admin/connector/run-once",
        {
            "connector_id": pair.connector_id,
            "credential_ids": [pair.credential_id],
            "from_beginning": True,
        },
    ),
    "prune": lambda user, pair: _call(
        user, "POST", f"/manage/admin/cc-pair/{pair.id}/prune"
    ),
    "read_manage_access": lambda user, pair: _call(
        user, "GET", f"/manage/admin/cc-pair/{pair.id}/manage-access"
    ),
}

_EDITOR_ACTIONS: dict[str, _Action] = {
    "edit_config": lambda user, pair: _call(
        user,
        "PATCH",
        f"/manage/admin/connector/{pair.connector_id}",
        _connector_body(pair),
    ),
    # an unknown credential gets past the Editor gate and then 404s
    "swap_credential": lambda user, pair: _call(
        user,
        "PUT",
        "/manage/admin/credential/swap",
        {
            "new_credential_id": 999999,
            "connector_id": pair.connector_id,
            "access_type": pair.access_type.value,
        },
    ),
    "set_manage_access": lambda user, pair: _call(
        user,
        "PUT",
        f"/manage/admin/cc-pair/{pair.id}/manage-access",
        {"manage_access": []},
    ),
    "delete_cc_pair": lambda user, pair: _call(
        user,
        "POST",
        "/manage/admin/deletion-attempt",
        {"connector_id": pair.connector_id, "credential_id": pair.credential_id},
    ),
    "delete_connector": lambda user, pair: _call(
        user, "DELETE", f"/manage/admin/connector/{pair.connector_id}"
    ),
}


def _denied(resp: httpx.Response) -> bool:
    """A manage gate answers 403, or 404 CONNECTOR_NOT_FOUND where the fetch that
    gates the route hides the pair."""
    if resp.status_code == 403:
        return True
    return resp.status_code == 404 and (
        resp.json().get("error_code") == "CONNECTOR_NOT_FOUND"
    )


def _actor(env: _RolesEnv, name: str) -> DATestUser:
    return {
        "admin": env.admin,
        "editor": env.editor,
        "operator": env.operator,
        "no_role": env.no_role,
    }[name]


_ACCESS_TYPES = [AccessType.PRIVATE, AccessType.PUBLIC]
_OPERATES = {"admin": True, "editor": True, "operator": True, "no_role": False}
_EDITS = {"admin": True, "editor": True, "operator": False, "no_role": False}


@pytest.mark.parametrize("access_type", _ACCESS_TYPES)
@pytest.mark.parametrize("actor_name", list(_OPERATES))
@pytest.mark.parametrize("action_name", list(_OPERATOR_ACTIONS))
def test_operator_actions(
    env: _RolesEnv, access_type: AccessType, actor_name: str, action_name: str
) -> None:
    cc_pair = _pair(env, access_type)
    resp = _OPERATOR_ACTIONS[action_name](_actor(env, actor_name), cc_pair)
    assert _denied(resp) is not _OPERATES[actor_name], (
        f"{actor_name} {action_name} on {access_type}: {resp.status_code} {resp.text}"
    )


@pytest.mark.parametrize("access_type", _ACCESS_TYPES)
@pytest.mark.parametrize("actor_name", list(_EDITS))
@pytest.mark.parametrize("action_name", list(_EDITOR_ACTIONS))
def test_editor_actions(
    env: _RolesEnv, access_type: AccessType, actor_name: str, action_name: str
) -> None:
    cc_pair = _pair(env, access_type)
    resp = _EDITOR_ACTIONS[action_name](_actor(env, actor_name), cc_pair)
    assert _denied(resp) is not _EDITS[actor_name], (
        f"{actor_name} {action_name} on {access_type}: {resp.status_code} {resp.text}"
    )


def test_detail_permissions_map_follows_role(env: _RolesEnv) -> None:
    cc_pair = _pair(env, AccessType.PRIVATE)
    expected = {
        "editor": {"operate": True, "edit": True, "delete": True, "publish": False},
        "operator": {"operate": True, "edit": False, "delete": False, "publish": False},
    }
    for actor_name, permissions in expected.items():
        info = CCPairManager.get_single(cc_pair.id, _actor(env, actor_name))
        assert info is not None
        assert info.permissions == permissions, actor_name


def test_manager_cannot_publish(env: _RolesEnv) -> None:
    """Making a pair PUBLIC stays admin-only, for Editors too."""
    resp = _call(
        env.editor,
        "PUT",
        # the scope gate runs before the ids are looked up
        "/manage/connector/999999/credential/999999",
        {
            "name": f"pub-{uuid4()}",
            "access_type": AccessType.PUBLIC.value,
            "manage_access": [
                {
                    "group_id": env.editor_group.id,
                    "role": ConnectorManageRole.EDITOR.value,
                }
            ],
        },
    )
    assert resp.status_code == 403, resp.text


def test_create_with_manage_access_stores_roles(env: _RolesEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.editor_group.id],
    )
    rows = CCPairManager.get_manage_access(cc_pair.id, env.admin)
    stored = {row.group_id: row.role for row in rows if not row.is_fixed}
    assert stored == {env.editor_group.id: ConnectorManageRole.EDITOR}


def test_create_rejects_a_group_listed_twice(env: _RolesEnv) -> None:
    resp = _call(
        env.admin,
        "PUT",
        "/manage/connector/999999/credential/999999",
        {
            "name": f"dup-{uuid4()}",
            "access_type": AccessType.PRIVATE.value,
            "manage_access": [
                {"group_id": env.editor_group.id, "role": "editor"},
                {"group_id": env.editor_group.id, "role": "operator"},
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_create_accepts_legacy_groups_as_editors(env: _RolesEnv) -> None:
    """Clients that predate manage_access send groups: each becomes an Editor and,
    for a PRIVATE pair, gets data access, as before roles existed."""
    connector = ConnectorManager.create(user_performing_action=env.admin)
    credential = CredentialManager.create(user_performing_action=env.admin)
    path = f"/manage/connector/{connector.id}/credential/{credential.id}"
    resp = _call(
        env.admin,
        "PUT",
        path,
        {
            "name": f"legacy-{uuid4()}",
            "access_type": AccessType.PRIVATE.value,
            "groups": [env.editor_group.id],
            "manage_access": [
                {"group_id": env.operator_group.id, "role": "operator"},
            ],
        },
    )
    assert resp.status_code == 422, resp.text

    resp = _call(
        env.admin,
        "PUT",
        path,
        {
            "name": f"legacy-{uuid4()}",
            "access_type": AccessType.PRIVATE.value,
            "groups": [env.editor_group.id],
        },
    )
    resp.raise_for_status()
    cc_pair_id = int(resp.json()["data"])
    rows = CCPairManager.get_manage_access(cc_pair_id, env.admin)
    assert {row.group_id: row.role for row in rows if not row.is_fixed} == {
        env.editor_group.id: ConnectorManageRole.EDITOR
    }
    assert CCPairManager.get_data_access_group_ids(cc_pair_id, env.admin) == {
        env.editor_group.id
    }


def test_manage_access_lists_fixed_admin_rows(env: _RolesEnv) -> None:
    cc_pair = _pair(env, AccessType.PRIVATE)
    rows = CCPairManager.get_manage_access(cc_pair.id, env.operator)

    fixed = [row for row in rows if row.is_fixed]
    assert "Admin" in {row.group_name for row in fixed}
    assert all(row.role is ConnectorManageRole.EDITOR for row in fixed)
    # The operator sees only the stored rows of groups they can see.
    assert {row.group_id: row.role for row in rows if not row.is_fixed} == {
        env.operator_group.id: ConnectorManageRole.OPERATOR,
    }
    rows = CCPairManager.get_manage_access(cc_pair.id, env.admin)
    assert {row.group_id: row.role for row in rows if not row.is_fixed} == {
        env.editor_group.id: ConnectorManageRole.EDITOR,
        env.operator_group.id: ConnectorManageRole.OPERATOR,
    }


def test_fixed_group_gets_no_stored_row(env: _RolesEnv) -> None:
    """A group with a global Manage Connectors grant is a fixed Editor, so it shows
    once, as fixed, and it can't also get a stored role."""
    cc_pair = _pair(env, AccessType.PRIVATE)
    group = UserGroupManager.create(user_performing_action=env.admin)
    CCPairManager.set_manage_access(
        cc_pair.id,
        {
            env.editor_group.id: ConnectorManageRole.EDITOR,
            env.operator_group.id: ConnectorManageRole.OPERATOR,
            group.id: ConnectorManageRole.OPERATOR,
        },
        user_performing_action=env.admin,
    )
    UserGroupManager.set_permissions(
        group, ["manage:connectors"], env.admin
    ).raise_for_status()
    try:
        rows = CCPairManager.get_manage_access(cc_pair.id, env.admin)
        assert [row.is_fixed for row in rows if row.group_id == group.id] == [True]

        other = _pair(env, AccessType.PRIVATE)
        with pytest.raises(httpx.HTTPStatusError) as error:
            CCPairManager.set_manage_access(
                other.id,
                {group.id: ConnectorManageRole.OPERATOR},
                user_performing_action=env.admin,
            )
        assert error.value.response.status_code == 400
        resp = _call(
            env.admin,
            "PUT",
            f"/manage/admin/user-group/{group.id}/managed-cc-pairs",
            {"cc_pairs": [{"cc_pair_id": other.id, "role": "operator"}]},
        )
        assert resp.status_code == 400, resp.text
    finally:
        UserGroupManager.set_permissions(group, [], env.admin).raise_for_status()


def test_fixed_rows_survive_an_empty_put(env: _RolesEnv) -> None:
    cc_pair = _pair(env, AccessType.PRIVATE)
    before = {
        row.group_id
        for row in CCPairManager.get_manage_access(cc_pair.id, env.admin)
        if row.is_fixed
    }

    rows = CCPairManager.set_manage_access(
        cc_pair.id, {}, user_performing_action=env.admin
    )

    assert {row.group_id for row in rows if row.is_fixed} == before
    assert before, "the Admin group always manages every connector"
    assert not [row for row in rows if not row.is_fixed]


def test_editor_changes_only_groups_they_can_see(env: _RolesEnv) -> None:
    """The editor sees only the group they manage. They may re-role or drop it. Rows
    of groups they cannot see stay when the request leaves them out."""
    cc_pair = _pair(env, AccessType.PRIVATE)
    path = f"/manage/admin/cc-pair/{cc_pair.id}/manage-access"

    def put(rows: dict[int, ConnectorManageRole]) -> httpx.Response:
        return _call(
            env.editor,
            "PUT",
            path,
            {
                "manage_access": [
                    {"group_id": group_id, "role": role.value}
                    for group_id, role in rows.items()
                ]
            },
        )

    # leaving out a group they cannot see keeps its row
    resp = put({env.editor_group.id: ConnectorManageRole.EDITOR})
    assert resp.status_code == 200, resp.text
    # adding a group they cannot see
    resp = put(
        {
            env.editor_group.id: ConnectorManageRole.EDITOR,
            env.operator_group.id: ConnectorManageRole.OPERATOR,
            env.no_role_group.id: ConnectorManageRole.OPERATOR,
        }
    )
    assert resp.status_code == 403, resp.text
    # re-roling a group they cannot see
    resp = put(
        {
            env.editor_group.id: ConnectorManageRole.EDITOR,
            env.operator_group.id: ConnectorManageRole.EDITOR,
        }
    )
    assert resp.status_code == 403, resp.text

    stored = {
        row.group_id: row.role
        for row in CCPairManager.get_manage_access(cc_pair.id, env.admin)
        if not row.is_fixed
    }
    assert stored == {
        env.editor_group.id: ConnectorManageRole.EDITOR,
        env.operator_group.id: ConnectorManageRole.OPERATOR,
    }, "a refused write changed the rows"

    # their own group, with the other row echoed: allowed, and it takes effect now
    resp = put(
        {
            env.editor_group.id: ConnectorManageRole.OPERATOR,
            env.operator_group.id: ConnectorManageRole.OPERATOR,
        }
    )
    assert resp.status_code == 200, resp.text
    edit = _EDITOR_ACTIONS["edit_config"](env.editor, cc_pair)
    assert _denied(edit), "an Operator kept Editor rights after the change"


def test_group_side_sets_roles(env: _RolesEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=AccessType.PRIVATE, groups=[]
    )
    UserGroupManager.set_managed_cc_pairs(
        env.no_role_group,
        {cc_pair.id: ConnectorManageRole.OPERATOR},
        user_performing_action=env.admin,
    )
    rows = CCPairManager.get_manage_access(cc_pair.id, env.admin)
    assert {row.group_id: row.role for row in rows if not row.is_fixed} == {
        env.no_role_group.id: ConnectorManageRole.OPERATOR
    }
    assert not _denied(_OPERATOR_ACTIONS["pause"](env.no_role, cc_pair))
    assert _denied(_EDITOR_ACTIONS["edit_config"](env.no_role, cc_pair))

    # The group side keeps the group-edit authorization, but a manager can't give a
    # group a role they don't hold: this Operator can't make their group an Editor.
    path = f"/manage/admin/user-group/{env.no_role_group.id}/managed-cc-pairs"
    resp = _call(env.no_role, "PUT", path, {"cc_pairs": [{"cc_pair_id": cc_pair.id}]})
    assert resp.status_code == 403, resp.text
    resp = _call(
        env.no_role,
        "PUT",
        path,
        {"cc_pairs": [{"cc_pair_id": cc_pair.id, "role": "operator"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"cc_pair_id": cc_pair.id, "role": "operator"}]

    # ...but not on a group they don't manage
    resp = _call(
        env.no_role,
        "PUT",
        f"/manage/admin/user-group/{env.editor_group.id}/managed-cc-pairs",
        {"cc_pairs": [{"cc_pair_id": cc_pair.id}]},
    )
    assert resp.status_code == 403, resp.text

    UserGroupManager.set_managed_cc_pairs(
        env.no_role_group, {}, user_performing_action=env.admin
    )
    assert _denied(_OPERATOR_ACTIONS["pause"](env.no_role, cc_pair))


def test_legacy_group_patch_keeps_roles(env: _RolesEnv) -> None:
    """The legacy PATCH cc_pair_ids field gives a new pair EDITOR and leaves the
    role of a pair the group already manages alone."""
    kept, added = (
        CCPairManager.create_from_scratch(
            user_performing_action=env.admin, access_type=AccessType.PRIVATE, groups=[]
        )
        for _ in range(2)
    )
    group = UserGroupManager.create(user_performing_action=env.admin)
    UserGroupManager.set_managed_cc_pairs(
        group, {kept.id: ConnectorManageRole.OPERATOR}, user_performing_action=env.admin
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=env.admin, user_groups_to_check=[group]
    )

    group.cc_pair_ids = [kept.id, added.id]
    UserGroupManager.edit(group, user_performing_action=env.admin)

    def stored_role(cc_pair: DATestCCPair) -> ConnectorManageRole:
        [role] = [
            row.role
            for row in CCPairManager.get_manage_access(cc_pair.id, env.admin)
            if row.group_id == group.id
        ]
        return role

    assert stored_role(kept) is ConnectorManageRole.OPERATOR
    assert stored_role(added) is ConnectorManageRole.EDITOR


def test_manage_access_put_does_not_reveal_which_pair_ids_exist(
    env: _RolesEnv,
) -> None:
    cc_pair = _pair(env, AccessType.PRIVATE)
    body = {"manage_access": []}

    missing = _call(
        env.operator, "PUT", "/manage/admin/cc-pair/999999/manage-access", body
    )
    existing = _call(
        env.operator, "PUT", f"/manage/admin/cc-pair/{cc_pair.id}/manage-access", body
    )

    assert missing.status_code == existing.status_code == 403
    assert missing.json() == existing.json()
