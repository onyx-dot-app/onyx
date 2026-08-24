"""The seeded default groups (Admin/Basic) are visible, hold members and nothing else,
and only a full admin may change that membership.

The list endpoint still returns them to any READ_USER_GROUPS holder that asks — the
service-account picker relies on that — so "full admins only" rides on the ``permissions``
map the client filters on, plus the route guards asserted below.
"""

import os
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

ENTERPRISE_SKIP = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)

GROUP_URL = f"{API_SERVER_URL}/manage/admin/user-group"
TOKEN_LIMIT_URL = f"{API_SERVER_URL}/admin/token-rate-limits"


@ENTERPRISE_SKIP
def test_default_groups_are_listed_only_when_requested(admin_user: DATestUser) -> None:
    without_default = UserGroupManager.get_all(user_performing_action=admin_user)
    assert not [group for group in without_default if group.is_default]

    with_default = UserGroupManager.get_all(
        user_performing_action=admin_user, include_default=True
    )
    default_names = {group.name for group in with_default if group.is_default}
    assert {"Admin", "Basic"} <= default_names, default_names


@ENTERPRISE_SKIP
def test_default_group_affordances_are_membership_only(admin_user: DATestUser) -> None:
    """Whole-map equality: a new action defaulting to True must fail here rather than
    quietly render a control the routes reject."""
    for name in ("Admin", "Basic"):
        group = UserGroupManager.get_default(
            user_performing_action=admin_user, name=name
        )
        assert group.permissions == {
            "manage": False,
            "manage_members": True,
            "delete": False,
            "edit_permissions": False,
            "edit_token_limits": False,
        }, name


@ENTERPRISE_SKIP
def test_default_group_rejects_every_non_membership_write(
    admin_user: DATestUser,
) -> None:
    group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    headers = admin_user.headers

    writes = {
        "rename": client.patch(
            f"{GROUP_URL}/rename",
            json={"id": group.id, "name": "Renamed"},
            headers=headers,
        ),
        "permissions": client.put(
            f"{GROUP_URL}/{group.id}/permissions",
            json={"permissions": [Permission.MANAGE_LLMS.value]},
            headers=headers,
        ),
        "incognito": client.patch(
            f"{GROUP_URL}/{group.id}/incognito",
            json={"enabled": True},
            headers=headers,
        ),
        "agents": client.patch(
            f"{GROUP_URL}/{group.id}/agents",
            json={"added_agent_ids": [], "removed_agent_ids": []},
            headers=headers,
        ),
        "document_sets": client.patch(
            f"{GROUP_URL}/{group.id}/document-sets",
            json={"added_document_set_ids": [], "removed_document_set_ids": []},
            headers=headers,
        ),
        "manager": client.put(
            f"{GROUP_URL}/{group.id}/manager",
            json={"user_id": admin_user.id, "is_manager": True},
            headers=headers,
        ),
        # a default group holds no connectors, so any id here is refused
        "connectors": client.patch(
            f"{GROUP_URL}/{group.id}",
            json={
                "user_ids": [user.id for user in group.users],
                "cc_pair_ids": [999999],
            },
            headers=headers,
        ),
        "delete": client.delete(f"{GROUP_URL}/{group.id}", headers=headers),
        # token limits live on their own router, so they need their own guard
        "token_limit_create": client.post(
            f"{TOKEN_LIMIT_URL}/user-group/{group.id}",
            json={"enabled": True, "token_budget": 1000, "period_hours": 24},
            headers=headers,
        ),
        "token_limit_update": client.put(
            f"{TOKEN_LIMIT_URL}/user-group/{group.id}/rate-limit/999999",
            json={"enabled": False, "token_budget": 1, "period_hours": 24},
            headers=headers,
        ),
        "token_limit_delete": client.delete(
            f"{TOKEN_LIMIT_URL}/user-group/{group.id}/rate-limit/999999",
            headers=headers,
        ),
    }
    for action, response in writes.items():
        assert response.status_code == 409, f"{action}: {response.text}"

    unchanged = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    assert unchanged.name == "Basic"
    assert unchanged.manager_ids == []
    assert unchanged.incognito_enabled is False


@ENTERPRISE_SKIP
def test_admin_can_add_and_remove_default_group_members(
    admin_user: DATestUser,
) -> None:
    """Signup already puts every user in Basic, so Admin is the group that exercises both
    directions, and its grant makes the effect observable on the member."""
    member = UserManager.create(name=f"default-group-member-{uuid4().hex[:8]}")
    group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Admin"
    )

    added = client.post(
        f"{GROUP_URL}/{group.id}/add-users",
        json={"user_ids": [member.id]},
        headers=admin_user.headers,
    )
    assert added.status_code == 200, added.text
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value in UserManager.get_permissions(
        member
    )

    group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Admin"
    )
    assert member.id in {user.id for user in group.users}

    removed = client.patch(
        f"{GROUP_URL}/{group.id}",
        json={
            "user_ids": [user.id for user in group.users if user.id != member.id],
            "cc_pair_ids": [cc_pair.id for cc_pair in group.cc_pairs],
        },
        headers=admin_user.headers,
    )
    assert removed.status_code == 200, removed.text

    group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Admin"
    )
    assert member.id not in {user.id for user in group.users}
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value not in UserManager.get_permissions(
        member
    )


@ENTERPRISE_SKIP
def test_resources_cannot_be_shared_with_a_default_group(
    admin_user: DATestUser,
) -> None:
    """Every resource can pick its own share targets, so the group page isn't the only way
    something could land on a default group. Credentials and document sets stand in for the
    shared guard that connectors, agents, LLM providers, MCP servers and skills all use."""
    basic = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )

    credential = client.post(
        f"{API_SERVER_URL}/manage/credential",
        json={
            "credential_json": {"token": "x"},
            "admin_public": False,
            "source": DocumentSource.FILE.value,
            "name": f"default-group-cred-{uuid4().hex[:8]}",
            "groups": [basic.id],
        },
        headers=admin_user.headers,
    )
    assert credential.status_code == 400, credential.text
    assert "Basic" in credential.text

    # a real connector, or the route rejects the set for being empty before it ever
    # reaches the share guard
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    document_set = client.post(
        f"{API_SERVER_URL}/manage/admin/document-set",
        json={
            "name": f"default-group-docset-{uuid4().hex[:8]}",
            "description": "",
            "cc_pair_ids": [cc_pair.id],
            "is_public": False,
            "users": [],
            "groups": [basic.id],
        },
        headers=admin_user.headers,
    )
    assert document_set.status_code == 400, document_set.text
    assert "Basic" in document_set.text
