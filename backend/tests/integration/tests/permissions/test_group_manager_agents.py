"""Escalation suite for scoping agents, skills, actions and token limits to
group managers.

A scoped group manager may manage these resources only within the groups they
manage, and never widen beyond their scope:

- **Skills**: create/grant/publish only for PRIVATE skills in managed groups;
  the admin list is scoped; DELETE is admin-only.
- **Agents**: may group-share a PRIVATE agent only to managed groups.
- **Actions/MCP**: actions have no group of their own, so scope is derived from
  the agents using them — editable only when every such agent is private and in a
  managed group; a public-agent or no-agent action is owner/admin-only; DELETE is
  admin-only.
- **Token limits**: settable only on a managed group.

Managers are seeded by flipping ``User__UserGroup.is_manager`` directly (no
manager-creation helper exists yet). Allowed actions go through Manager classes
(which assert real success); denied actions go through the shared ``_access_matrix``
helpers, which verify the 403 is a genuine permission-gate denial.

Not yet covered (need extra setup / a live run to verify): the ADD_AGENTS-only
"can create a personal agent but cannot group-share" case, and PAT scope narrowing.
"""

import os
from typing import Any
from typing import NamedTuple
from uuid import uuid4

import pytest
from sqlalchemy import update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
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
    """Create a simple MCP server as ``user`` (must succeed); returns its id."""
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


# --- skills -----------------------------------------------------------------


def test_manager_creates_private_skill_in_managed_group(env: _ScopedEnv) -> None:
    SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )


def test_manager_cannot_grant_skill_to_unmanaged_group(env: _ScopedEnv) -> None:
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    path = f"/admin/skills/custom/{skill.id}/grants"
    resp = call_endpoint(
        "PUT",
        path,
        {"group_ids": [env.managed_group.id, env.other_group.id]},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_cannot_publish_skill(env: _ScopedEnv) -> None:
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    path = f"/admin/skills/custom/{skill.id}"
    resp = call_endpoint(
        "PATCH", path, {"is_public": True}, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PATCH", path, "manager", "denied")


def test_manager_cannot_delete_skill(env: _ScopedEnv) -> None:
    # Owns it, in a managed group — still denied: delete is admin-only.
    skill = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    path = f"/admin/skills/custom/{skill.id}"
    resp = call_endpoint("DELETE", path, None, env.manager.headers, env.manager.cookies)
    assert_response(resp, "DELETE", path, "manager", "denied")


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


# --- agents -----------------------------------------------------------------


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
    path = f"/persona/{agent.id}/share"
    resp = call_endpoint(
        "PATCH",
        path,
        {"group_ids": [env.managed_group.id, env.other_group.id]},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")


def test_manager_cannot_publish_agent(env: _ScopedEnv) -> None:
    # Publishing (is_public) via the update path is outside a manager's scope even
    # when groups are unchanged — the group-share gate alone would miss it.
    agent = PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )
    path = f"/persona/{agent.id}"
    resp = call_endpoint(
        "PATCH",
        path,
        _persona_upsert_body(is_public=True, groups=[env.managed_group.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", path, "manager", "denied")


# --- custom actions (agent-mediated scope) ----------------------------------


def test_manager_creates_own_action(env: _ScopedEnv) -> None:
    _create_custom_tool(env.manager)


def test_manager_cannot_edit_unowned_ungrouped_action(env: _ScopedEnv) -> None:
    # Admin owns the action and no agent uses it → no group context → owner/admin only.
    tool_id = _create_custom_tool(env.admin)
    path = f"/admin/tool/custom/{tool_id}"
    resp = call_endpoint(
        "PUT", path, _tool_body(), env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_edits_action_used_by_managed_private_agent(env: _ScopedEnv) -> None:
    tool_id = _create_custom_tool(env.admin)
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
        tool_ids=[tool_id],
    )
    path = f"/admin/tool/custom/{tool_id}"
    resp = call_endpoint(
        "PUT", path, _tool_body(), env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PUT", path, "manager", "allowed")


def test_manager_cannot_edit_action_used_by_public_agent(env: _ScopedEnv) -> None:
    tool_id = _create_custom_tool(env.admin)
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=True,
        groups=[env.managed_group.id],
        tool_ids=[tool_id],
    )
    path = f"/admin/tool/custom/{tool_id}"
    resp = call_endpoint(
        "PUT", path, _tool_body(), env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_cannot_edit_action_used_by_ungrouped_private_agent(
    env: _ScopedEnv,
) -> None:
    # A private agent in NO group is a personal agent outside the manager's scope;
    # its presence must block editing even alongside a managed-group agent (the
    # ungrouped agent adds no group to the union, so it must be tracked explicitly).
    tool_id = _create_custom_tool(env.admin)
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
        tool_ids=[tool_id],
    )
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[],
        tool_ids=[tool_id],
    )
    path = f"/admin/tool/custom/{tool_id}"
    resp = call_endpoint(
        "PUT", path, _tool_body(), env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_cannot_delete_action(env: _ScopedEnv) -> None:
    # Owns it — still denied: delete is admin-only (no allow_scope on the route).
    tool_id = _create_custom_tool(env.manager)
    path = f"/admin/tool/custom/{tool_id}"
    resp = call_endpoint("DELETE", path, None, env.manager.headers, env.manager.cookies)
    assert_response(resp, "DELETE", path, "manager", "denied")


# --- MCP servers ------------------------------------------------------------


def test_manager_creates_mcp_server(env: _ScopedEnv) -> None:
    _create_mcp_server(env.manager)


def test_manager_cannot_delete_mcp_server(env: _ScopedEnv) -> None:
    # Owns it — still denied: MCP delete is admin-only.
    server_id = _create_mcp_server(env.manager)
    path = f"/admin/mcp/server/{server_id}"
    resp = call_endpoint("DELETE", path, None, env.manager.headers, env.manager.cookies)
    assert_response(resp, "DELETE", path, "manager", "denied")


# --- token limits -----------------------------------------------------------


def test_manager_sets_token_limit_on_managed_group(env: _ScopedEnv) -> None:
    path = f"/admin/token-rate-limits/user-group/{env.managed_group.id}"
    resp = call_endpoint(
        "POST", path, _TOKEN_LIMIT_BODY, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "POST", path, "manager", "allowed")


def test_manager_cannot_set_token_limit_on_unmanaged_group(env: _ScopedEnv) -> None:
    path = f"/admin/token-rate-limits/user-group/{env.other_group.id}"
    resp = call_endpoint(
        "POST", path, _TOKEN_LIMIT_BODY, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "POST", path, "manager", "denied")
