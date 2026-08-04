"""Escalation suite for scoping agents, skills, actions and token limits to
group managers.

A scoped group manager may manage these resources only within the groups they
manage, and never widen beyond their scope:

- **Skills**: create/grant/publish only for PRIVATE skills in managed groups;
  the admin list is scoped; DELETE is admin-only.
- **Agents**: may group-share a PRIVATE agent only to managed groups.
- **Actions/MCP**: owner-or-admin — a manager creates and fully manages (edit/delete)
  their own actions and servers, but cannot manage ones they didn't create, even those
  connected to their groups via agents.
- **Token limits**: settable only on a managed group.

Managers are seeded by flipping ``User__UserGroup.is_manager`` directly (no
manager-creation helper exists yet). Allowed actions go through Manager classes
(which assert real success); denied actions go through the shared ``_access_matrix``
helpers, which verify the 403 is a genuine permission-gate denial.

Not yet covered (need a live run to verify): the ADD_AGENTS-only user's inability
to group-share, and PAT scope narrowing.
"""

import os
from typing import Any
from typing import NamedTuple
from uuid import uuid4

import pytest
import requests
from sqlalchemy import update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import Permission
from onyx.db.models import User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup
from tests.integration.tests.permissions._access_matrix import assert_response
from tests.integration.tests.permissions._access_matrix import call_endpoint

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Group manager scoping is an enterprise-only capability",
)


class _ScopedEnv(NamedTuple):
    admin: DATestUser
    manager: DATestUser
    managed_group: DATestUserGroup
    other_group: DATestUserGroup


def _promote_to_manager(user_id: str, group_id: int) -> None:
    """Flip is_manager on the (user, group) edge and recompute the cached flag."""
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == user_id,
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=True)
        )
        db_session.flush()
        recompute_user_permissions__no_commit(user_id, db_session)
        db_session.commit()


@pytest.fixture
def env(reset: None, admin_user: DATestUser) -> _ScopedEnv:  # noqa: ARG001
    manager = UserManager.create(name="scoped_manager")
    managed_group = UserGroupManager.create(
        name="managed", user_ids=[manager.id], user_performing_action=admin_user
    )
    other_group = UserGroupManager.create(
        name="unmanaged", user_performing_action=admin_user
    )
    _promote_to_manager(manager.id, managed_group.id)
    return _ScopedEnv(admin_user, manager, managed_group, other_group)


def _tool_body() -> dict[str, Any]:
    return {
        "name": f"tool-{uuid4()}",
        "description": "escalation test",
        "definition": {
            "openapi": "3.0.0",
            "info": {"title": "t", "version": "1.0.0"},
            "paths": {},
        },
        "custom_headers": [],
        "passthrough_auth": False,
        "oauth_config_id": None,
    }


def _create_custom_tool(user: DATestUser) -> int:
    """Create a custom action as ``user`` (must succeed); returns its id."""
    resp = call_endpoint(
        "POST", "/admin/tool/custom", _tool_body(), user.headers, user.cookies
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _create_mcp_server(user: DATestUser) -> int:
    """Create an MCP server as ``user`` (must succeed); returns its id."""
    body = {
        "name": f"mcp-{uuid4()}",
        "description": "escalation test",
        "server_url": "https://example.com/mcp",
    }
    resp = call_endpoint("POST", "/admin/mcp/server", body, user.headers, user.cookies)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _persona_upsert_body(*, is_public: bool, groups: list[int]) -> dict[str, Any]:
    return {
        "name": f"agent-{uuid4()}",
        "description": "escalation test",
        "document_set_ids": [],
        "tool_ids": [],
        "system_prompt": "",
        "task_prompt": "",
        "datetime_aware": False,
        "is_public": is_public,
        "groups": groups,
    }


_TOKEN_LIMIT_BODY: dict[str, Any] = {
    "enabled": True,
    "token_budget": 1000,
    "period_hours": 24,
}


def _assert_manager(
    env: _ScopedEnv,
    method: str,
    path: str,
    expected: str,
    body: dict[str, Any] | None = None,
) -> requests.Response:
    """Call ``path`` as the scoped manager and assert the permission gate's verdict."""
    resp = call_endpoint(method, path, body, env.manager.headers, env.manager.cookies)
    assert_response(resp, method, path, "manager", expected)
    return resp


def test_manager_creates_private_skill_in_managed_group(env: _ScopedEnv) -> None:
    SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )


def test_manager_cannot_grant_skill_to_unmanaged_group(env: _ScopedEnv) -> None:
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    path = f"/admin/skills/custom/{skill.id}/grants"
    _assert_manager(
        env,
        "PUT",
        path,
        "denied",
        {"group_ids": [env.managed_group.id, env.other_group.id]},
    )


def test_manager_cannot_publish_skill(env: _ScopedEnv) -> None:
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    _assert_manager(
        env, "PATCH", f"/admin/skills/custom/{skill.id}", "denied", {"is_public": True}
    )


def test_manager_cannot_delete_skill(env: _ScopedEnv) -> None:
    # Owns it, in a managed group — still denied: delete is admin-only.
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    _assert_manager(env, "DELETE", f"/admin/skills/custom/{skill.id}", "denied")


def test_manager_skill_admin_list_is_scoped(env: _ScopedEnv) -> None:
    mine = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    theirs = SkillManager.create_custom(
        env.admin, is_public=False, group_ids=[env.other_group.id]
    )
    resp = call_endpoint(
        "GET", "/admin/skills", None, env.manager.headers, env.manager.cookies
    )
    assert resp.status_code == 200, resp.text
    custom_ids = {c["id"] for c in resp.json()["customs"]}
    assert str(mine.id) in custom_ids
    assert str(theirs.id) not in custom_ids


def test_manager_shares_agent_to_managed_group(env: _ScopedEnv) -> None:
    PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )


def test_manager_cannot_share_agent_to_unmanaged_group(env: _ScopedEnv) -> None:
    agent = PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )
    _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}/share",
        "denied",
        {"group_ids": [env.managed_group.id, env.other_group.id]},
    )


def test_manager_cannot_publish_agent(env: _ScopedEnv) -> None:
    # Publishing (is_public) via the update path is outside a manager's scope even
    # when groups are unchanged — the group-share gate alone would miss it.
    agent = PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )
    _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}",
        "denied",
        _persona_upsert_body(is_public=True, groups=[env.managed_group.id]),
    )


def test_manager_cannot_capture_public_agent_via_share(env: _ScopedEnv) -> None:
    # Manager owns a private agent in their group; an admin publishes it org-wide.
    agent = PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )
    publish = call_endpoint(
        "PATCH",
        f"/persona/{agent.id}",
        _persona_upsert_body(is_public=True, groups=[env.managed_group.id]),
        env.admin.headers,
        env.admin.cookies,
    )
    assert publish.status_code == 200, publish.text
    # The manager must not pull the now-public agent back to private AND keep the
    # group share in one call — the gate anchors on the original (public) state.
    _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}/share",
        "denied",
        {"is_public": False, "group_ids": [env.managed_group.id]},
    )


def test_manager_creates_personal_agent(env: _ScopedEnv) -> None:
    # A scoped manager may create a private no-group personal agent like any
    # ADD_AGENTS user; the managed-group gate applies only once a group is involved.
    _assert_manager(
        env,
        "POST",
        "/persona",
        "allowed",
        _persona_upsert_body(is_public=False, groups=[]),
    )


def test_add_agents_user_creates_personal_agent_with_empty_groups(
    env: _ScopedEnv,
) -> None:
    # An ADD_AGENTS-only user (no MANAGE_AGENTS authority) must still create a
    # personal agent when the client sends groups=[] (no group share).
    member = UserManager.create(name="add_agents_only")
    grant_group = UserGroupManager.create(
        name="add-agents", user_ids=[member.id], user_performing_action=env.admin
    )
    UserGroupManager.set_permissions(
        user_group=grant_group,
        permissions=[Permission.ADD_AGENTS.value],
        user_performing_action=env.admin,
    ).raise_for_status()
    path = "/persona"
    resp = call_endpoint(
        "POST",
        path,
        _persona_upsert_body(is_public=False, groups=[]),
        member.headers,
        member.cookies,
    )
    assert_response(resp, "POST", path, "member", "allowed")


def test_manager_rosters_agent_shared_to_managed_group(env: _ScopedEnv) -> None:
    # A private agent shared to the manager's group but owned by the admin can be
    # rostered out of that group by the manager: the scope-aware lookup admits them
    # so the MANAGE_AGENTS gate (not an owner-only lookup) authorizes the change.
    agent = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
    )
    path = f"/manage/admin/user-group/{env.managed_group.id}/agents"
    resp = call_endpoint(
        "PATCH",
        path,
        {"added_agent_ids": [], "removed_agent_ids": [agent.id]},
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text


# Custom actions: owner-or-admin gating (not group-scoped like skills/agents).
def test_manager_creates_own_action(env: _ScopedEnv) -> None:
    _create_custom_tool(env.manager)


def test_manager_edits_own_action(env: _ScopedEnv) -> None:
    tool_id = _create_custom_tool(env.manager)
    _assert_manager(
        env, "PUT", f"/admin/tool/custom/{tool_id}", "allowed", _tool_body()
    )


def test_manager_deletes_own_action(env: _ScopedEnv) -> None:
    tool_id = _create_custom_tool(env.manager)
    _assert_manager(env, "DELETE", f"/admin/tool/custom/{tool_id}", "allowed")


def test_manager_cannot_edit_unowned_action(env: _ScopedEnv) -> None:
    # Owner-or-admin: a manager can't edit an admin-created action, even one used by an agent
    # in a group they manage (managers get read visibility + their own, not others').
    tool_id = _create_custom_tool(env.admin)
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
        tool_ids=[tool_id],
    )
    _assert_manager(env, "PUT", f"/admin/tool/custom/{tool_id}", "denied", _tool_body())


def test_manager_cannot_delete_unowned_action(env: _ScopedEnv) -> None:
    tool_id = _create_custom_tool(env.admin)
    _assert_manager(env, "DELETE", f"/admin/tool/custom/{tool_id}", "denied")


# MCP servers: owner-or-admin gating (not group-scoped like skills/agents).
def test_manager_creates_mcp_server(env: _ScopedEnv) -> None:
    _create_mcp_server(env.manager)


def test_manager_deletes_own_mcp_server(env: _ScopedEnv) -> None:
    server_id = _create_mcp_server(env.manager)
    _assert_manager(env, "DELETE", f"/admin/mcp/server/{server_id}", "allowed")


def test_manager_cannot_delete_unowned_mcp_server(env: _ScopedEnv) -> None:
    server_id = _create_mcp_server(env.admin)
    _assert_manager(env, "DELETE", f"/admin/mcp/server/{server_id}", "denied")


def test_manager_update_via_servers_create_denied_not_masked(
    env: _ScopedEnv,
) -> None:
    # Updating an unowned server through /servers/create must surface the gate's 403, not a
    # 500 masked by the handler's blanket except.
    server_id = _create_mcp_server(env.admin)
    body = {
        "name": f"mcp-{uuid4()}",
        "server_url": "https://example.com/mcp",
        "auth_type": MCPAuthenticationType.NONE.value,
        "auth_performer": MCPAuthenticationPerformer.ADMIN.value,
        "existing_server_id": server_id,
    }
    _assert_manager(env, "POST", "/admin/mcp/servers/create", "denied", body)


def _group_limit_path(group_id: int, limit_id: int | None = None) -> str:
    base = f"/admin/token-rate-limits/user-group/{group_id}"
    return base if limit_id is None else f"{base}/rate-limit/{limit_id}"


def _create_group_token_limit(user: DATestUser, group_id: int) -> int:
    """Create a token limit on ``group_id`` as ``user`` (must succeed); returns its id."""
    resp = call_endpoint(
        "POST",
        _group_limit_path(group_id),
        _TOKEN_LIMIT_BODY,
        user.headers,
        user.cookies,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["token_id"])


def test_manager_sets_token_limit_on_managed_group(env: _ScopedEnv) -> None:
    path = _group_limit_path(env.managed_group.id)
    _assert_manager(env, "POST", path, "allowed", _TOKEN_LIMIT_BODY)


def test_manager_cannot_set_token_limit_on_unmanaged_group(env: _ScopedEnv) -> None:
    path = _group_limit_path(env.other_group.id)
    _assert_manager(env, "POST", path, "denied", _TOKEN_LIMIT_BODY)


def test_manager_reads_token_limits_on_managed_group(env: _ScopedEnv) -> None:
    _assert_manager(env, "GET", _group_limit_path(env.managed_group.id), "allowed")


def test_manager_cannot_read_token_limits_on_unmanaged_group(env: _ScopedEnv) -> None:
    _assert_manager(env, "GET", _group_limit_path(env.other_group.id), "denied")


def test_manager_updates_token_limit_on_managed_group(env: _ScopedEnv) -> None:
    limit_id = _create_group_token_limit(env.manager, env.managed_group.id)
    path = _group_limit_path(env.managed_group.id, limit_id)
    _assert_manager(env, "PUT", path, "allowed", _TOKEN_LIMIT_BODY)


def test_manager_cannot_update_token_limit_on_unmanaged_group(env: _ScopedEnv) -> None:
    limit_id = _create_group_token_limit(env.admin, env.other_group.id)
    path = _group_limit_path(env.other_group.id, limit_id)
    _assert_manager(env, "PUT", path, "denied", _TOKEN_LIMIT_BODY)


def test_manager_deletes_token_limit_on_managed_group(env: _ScopedEnv) -> None:
    limit_id = _create_group_token_limit(env.manager, env.managed_group.id)
    _assert_manager(
        env, "DELETE", _group_limit_path(env.managed_group.id, limit_id), "allowed"
    )


def test_manager_cannot_delete_token_limit_on_unmanaged_group(env: _ScopedEnv) -> None:
    limit_id = _create_group_token_limit(env.admin, env.other_group.id)
    _assert_manager(
        env, "DELETE", _group_limit_path(env.other_group.id, limit_id), "denied"
    )
