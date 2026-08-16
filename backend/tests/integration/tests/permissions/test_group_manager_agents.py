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

Not yet covered (needs a live run to verify): PAT scope narrowing.
"""

import os
from typing import Any, NamedTuple
from uuid import uuid4

import httpx
import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType, Permission
from onyx.db.models import User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.skill import SkillManager
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


class _ScopedEnv(NamedTuple):
    admin: DATestUser
    manager: DATestUser
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
    managed_group = UserGroupManager.create(
        name="managed", user_ids=[manager.id], user_performing_action=admin_user
    )
    other_group = UserGroupManager.create(
        name="unmanaged", user_performing_action=admin_user
    )
    _promote_to_manager(manager.id, managed_group.id)
    return _ScopedEnv(admin_user, manager, managed_group, other_group)


def _tool_body(oauth_config_id: int | None = None) -> dict[str, Any]:
    return {
        "name": f"tool-{uuid4()}",
        "description": "escalation test",
        # validate_openapi_schema needs info.description, exactly one server URL, and at
        # least one method — an empty `paths` is rejected.
        "definition": {
            "openapi": "3.0.0",
            "info": {"title": "t", "description": "t", "version": "1.0.0"},
            "servers": [{"url": "https://example.com"}],
            "paths": {
                "/ping": {
                    "get": {
                        "summary": "ping",
                        "operationId": "ping",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        },
        "custom_headers": [],
        "passthrough_auth": False,
        "oauth_config_id": oauth_config_id,
    }


def _create_custom_tool(user: DATestUser, oauth_config_id: int | None = None) -> int:
    """Create a custom action as ``user`` (must succeed); returns its id."""
    resp = call_endpoint(
        "POST",
        "/admin/tool/custom",
        _tool_body(oauth_config_id),
        user.headers,
        user.cookies,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _create_oauth_config(user: DATestUser) -> int:
    """Create an OAuth config as ``user`` (must succeed); returns its id."""
    body = {
        "name": f"oauth-{uuid4()}",
        "authorization_url": "https://example.com/authorize",
        "token_url": "https://example.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    resp = call_endpoint(
        "POST", "/admin/oauth-config/create", body, user.headers, user.cookies
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _mcp_body(*, is_public: bool, groups: list[int]) -> dict[str, Any]:
    return {
        "name": f"mcp-{uuid4()}",
        "description": "escalation test",
        "server_url": "https://example.com/mcp",
        "is_public": is_public,
        "groups": groups,
    }


def _create_mcp_server(
    user: DATestUser, *, is_public: bool = True, groups: list[int] | None = None
) -> int:
    """Create an MCP server as ``user`` (must succeed); returns its id.

    is_public defaults True on the request model, which a scoped manager may never
    set — so a manager has to pass its own group explicitly.
    """
    body = _mcp_body(is_public=is_public, groups=groups or [])
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
) -> httpx.Response:
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
    _assert_manager(
        env,
        "PATCH",
        f"/skills/custom/{skill.id}/share",
        "denied",
        {
            "group_shares": [
                {"group_id": env.managed_group.id, "permission": "VIEWER"},
                {"group_id": env.other_group.id, "permission": "VIEWER"},
            ]
        },
    )


def test_manager_cannot_publish_skill(env: _ScopedEnv) -> None:
    # _ensure_can_edit_org_visibility admits only the owner or a global holder.
    skill = SkillManager.create_custom(
        env.admin, is_public=False, group_ids=[env.managed_group.id]
    )
    _assert_manager(
        env,
        "PATCH",
        f"/skills/custom/{skill.id}",
        "denied",
        {"public_permission": "VIEWER"},
    )


@pytest.mark.xfail(
    strict=True,
    reason="D6 (admin-only delete for managed resources) is not implemented. "
    "31d5a492e4 removed the admin skill router, so the only delete is "
    "delete_current_user_skill (BASIC_ACCESS + SkillManagementPolicy.EDIT), and "
    "EDIT admits a scoped manager via _is_group_shared_only_within_managed_scope "
    "— so the manager currently succeeds. Drop this marker when D6 lands.",
)
def test_manager_cannot_delete_skill_it_does_not_own(env: _ScopedEnv) -> None:
    # Manager can edit it (managed group), but delete should stay admin-only.
    skill = SkillManager.create_custom(
        env.admin, is_public=False, group_ids=[env.managed_group.id]
    )
    _assert_manager(env, "DELETE", f"/skills/custom/{skill.id}", "denied")


def test_manager_skill_list_is_scoped(env: _ScopedEnv) -> None:
    mine = SkillManager.create_custom(
        env.manager, is_public=False, group_ids=[env.managed_group.id]
    )
    theirs = SkillManager.create_custom(
        env.admin, is_public=False, group_ids=[env.other_group.id]
    )
    resp = call_endpoint(
        "GET", "/skills", None, env.manager.headers, env.manager.cookies
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


def test_manager_publishes_own_agent(env: _ScopedEnv) -> None:
    # D9: publishing follows ownership — being a manager must not subtract a right an
    # ordinary owner holds.
    agent = PersonaManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
    )
    resp = _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}",
        "allowed",
        _persona_upsert_body(is_public=True, groups=[env.managed_group.id]),
    )
    # upsert_persona drops an unauthorized is_public silently, so 200 proves nothing.
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_public"] is True


def test_manager_unpublishes_own_agent(env: _ScopedEnv) -> None:
    # The direction the group-share gate used to block: the manager pulls their own
    # published agent back to private, keeping the group share. Ownership authorizes it.
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
    _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}/share",
        "allowed",
        {"is_public": False, "group_ids": [env.managed_group.id]},
    )
    read_back = call_endpoint(
        "GET", f"/persona/{agent.id}", None, env.admin.headers, env.admin.cookies
    )
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["is_public"] is False


def test_manager_cannot_delete_unowned_agent(env: _ScopedEnv) -> None:
    # Delete follows ownership: a manager may edit an admin-owned agent shared into a group
    # they manage, but not delete it (mark_persona_as_deleted → get_persona_by_id is_for_edit
    # admits only the owner or owner-group, not a shared-group manager).
    agent = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
    )
    resp = call_endpoint(
        "DELETE", f"/persona/{agent.id}", None, env.manager.headers, env.manager.cookies
    )
    assert resp.status_code == 403, resp.text


def test_manager_cannot_publish_unowned_agent(env: _ScopedEnv) -> None:
    # Publishing an admin-owned managed agent is owner-only: the manager may edit it, but
    # upsert_persona drops the is_public silently, so it must not become public.
    agent = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
    )
    call_endpoint(
        "PATCH",
        f"/persona/{agent.id}",
        _persona_upsert_body(is_public=True, groups=[env.managed_group.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    read_back = call_endpoint(
        "GET", f"/persona/{agent.id}", None, env.admin.headers, env.admin.cookies
    )
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["is_public"] is False


def test_manager_cannot_capture_public_agent_via_share(env: _ScopedEnv) -> None:
    # A PUBLIC agent sits in nobody's managed scope, so sharing it into a managed group
    # captures it — rejected even for the owner. Ownership buys publishing, not scope.
    agent = PersonaManager.create(
        user_performing_action=env.manager, is_public=True, groups=[]
    )
    _assert_manager(
        env,
        "PATCH",
        f"/persona/{agent.id}/share",
        "denied",
        {"group_ids": [env.managed_group.id]},
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


def _add_agents_only_user(env: _ScopedEnv, name: str) -> DATestUser:
    """A user whose only admin permission is ADD_AGENTS — no MANAGE_AGENTS authority."""
    member = UserManager.create(name=name)
    grant_group = UserGroupManager.create(
        name=f"{name}-group", user_ids=[member.id], user_performing_action=env.admin
    )
    UserGroupManager.set_permissions(
        user_group=grant_group,
        permissions=[Permission.ADD_AGENTS.value],
        user_performing_action=env.admin,
    ).raise_for_status()
    return member


def test_add_agents_user_creates_personal_agent_with_empty_groups(
    env: _ScopedEnv,
) -> None:
    # An ADD_AGENTS-only user (no MANAGE_AGENTS authority) must still create a
    # personal agent when the client sends groups=[] (no group share).
    member = _add_agents_only_user(env, "add_agents_only")
    path = "/persona"
    resp = call_endpoint(
        "POST",
        path,
        _persona_upsert_body(is_public=False, groups=[]),
        member.headers,
        member.cookies,
    )
    assert_response(resp, "POST", path, "member", "allowed")


def test_add_agents_owner_saves_agent_group_shared_by_admin(env: _ScopedEnv) -> None:
    # The editor round-trips current groups on every save, so an unchanged set must not
    # read as a mutation — else an ADD_AGENTS-only owner loses edit access to their own
    # agent once an admin group-shares it. Altering the set still needs MANAGE_AGENTS.
    member = _add_agents_only_user(env, "add_agents_owner")
    agent = PersonaManager.create(
        user_performing_action=member, is_public=False, groups=[]
    )
    share = call_endpoint(
        "PATCH",
        f"/persona/{agent.id}/share",
        {"group_ids": [env.other_group.id]},
        env.admin.headers,
        env.admin.cookies,
    )
    assert share.status_code == 200, share.text

    path = f"/persona/{agent.id}"
    unchanged = call_endpoint(
        "PATCH",
        path,
        _persona_upsert_body(is_public=False, groups=[env.other_group.id]),
        member.headers,
        member.cookies,
    )
    assert_response(unchanged, "PATCH", path, "member", "allowed")

    widened = call_endpoint(
        "PATCH",
        path,
        _persona_upsert_body(
            is_public=False, groups=[env.other_group.id, env.managed_group.id]
        ),
        member.headers,
        member.cookies,
    )
    assert_response(widened, "PATCH", path, "member", "denied")


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


def test_manager_links_own_oauth_config(env: _ScopedEnv) -> None:
    # Nothing else references it, so it's theirs to take.
    oauth_config_id = _create_oauth_config(env.manager)
    _create_custom_tool(env.manager, oauth_config_id)


def test_manager_cannot_link_unowned_oauth_config(env: _ScopedEnv) -> None:
    # Linking in would authenticate as the admin's OAuth app, using credentials the manager
    # never sees.
    oauth_config_id = _create_oauth_config(env.admin)
    _create_custom_tool(env.admin, oauth_config_id)
    _assert_manager(
        env, "POST", "/admin/tool/custom", "denied", _tool_body(oauth_config_id)
    )


def test_unknown_oauth_config_is_rejected_not_a_500(env: _ScopedEnv) -> None:
    # An unknown id has no referencing actions, so the link gate would wave it through to
    # the foreign key. Applies to the admin too — the global branch skips the reference read.
    for actor in (env.manager, env.admin):
        resp = call_endpoint(
            "POST",
            "/admin/tool/custom",
            _tool_body(2_000_000_000),
            actor.headers,
            actor.cookies,
        )
        assert resp.status_code == 404, resp.text


def test_manager_edits_own_action_keeping_shared_oauth_config(env: _ScopedEnv) -> None:
    # An admin can link a second action to the manager's config, which makes it shared. The
    # manager must still be able to edit their own action while re-sending the same id.
    oauth_config_id = _create_oauth_config(env.manager)
    tool_id = _create_custom_tool(env.manager, oauth_config_id)
    _create_custom_tool(env.admin, oauth_config_id)
    _assert_manager(
        env,
        "PUT",
        f"/admin/tool/custom/{tool_id}",
        "allowed",
        _tool_body(oauth_config_id),
    )


def test_manager_cannot_repoint_own_action_at_unowned_oauth_config(
    env: _ScopedEnv,
) -> None:
    # Owning the action doesn't extend to the credentials it points at.
    oauth_config_id = _create_oauth_config(env.admin)
    _create_custom_tool(env.admin, oauth_config_id)
    tool_id = _create_custom_tool(env.manager)
    _assert_manager(
        env,
        "PUT",
        f"/admin/tool/custom/{tool_id}",
        "denied",
        _tool_body(oauth_config_id),
    )


# MCP servers: owner-or-admin gating (not group-scoped like skills/agents).
def test_manager_creates_private_mcp_server_in_managed_group(
    env: _ScopedEnv,
) -> None:
    _create_mcp_server(env.manager, is_public=False, groups=[env.managed_group.id])


def test_manager_cannot_create_public_mcp_server(env: _ScopedEnv) -> None:
    """Same rule as connectors and document sets: never widen to public."""
    _assert_manager(
        env,
        "POST",
        "/admin/mcp/server",
        "denied",
        _mcp_body(is_public=True, groups=[]),
    )


def test_manager_cannot_create_public_mcp_server_by_omitting_access(
    env: _ScopedEnv,
) -> None:
    # /servers/create defaults is_public=True when is_public/users/groups are omitted, so
    # the create path must gate unconditionally — else a manager publishes org-wide simply
    # by leaving the access fields out of the body.
    # auth_performer is required; omitting it 422s before the gate runs
    body = {
        "name": f"mcp-{uuid4()}",
        "server_url": "https://example.com/mcp",
        "auth_type": MCPAuthenticationType.NONE.value,
        "auth_performer": MCPAuthenticationPerformer.ADMIN.value,
    }
    _assert_manager(env, "POST", "/admin/mcp/servers/create", "denied_gate2", body)


def test_manager_cannot_create_mcp_server_in_unmanaged_group(
    env: _ScopedEnv,
) -> None:
    _assert_manager(
        env,
        "POST",
        "/admin/mcp/server",
        "denied",
        _mcp_body(is_public=False, groups=[env.other_group.id]),
    )


def test_manager_deletes_own_mcp_server(env: _ScopedEnv) -> None:
    server_id = _create_mcp_server(
        env.manager, is_public=False, groups=[env.managed_group.id]
    )
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


def test_manager_action_listing_scoped_to_own_and_agent_connected(
    env: _ScopedEnv,
) -> None:
    """An action carries no group, so an agent is the only path from a group to one.
    The listing returned every action in the tenant before this was scoped."""
    own = _create_custom_tool(env.manager)
    connected = _create_custom_tool(env.admin)
    unconnected = _create_custom_tool(env.admin)
    elsewhere = _create_custom_tool(env.admin)

    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
        tool_ids=[connected],
    )
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.other_group.id],
        tool_ids=[elsewhere],
    )

    listed = {
        tool["id"]
        for tool in _assert_manager(env, "GET", "/tool/openapi", "allowed").json()
    }
    assert {own, connected} <= listed
    assert not ({unconnected, elsewhere} & listed), "unreachable action leaked"

    admin_resp = call_endpoint(
        "GET", "/tool/openapi", None, env.admin.headers, env.admin.cookies
    )
    admin_listed = {tool["id"] for tool in admin_resp.json()}
    assert {own, connected, unconnected, elsewhere} <= admin_listed


def test_manager_reads_action_by_id_only_when_reachable(env: _ScopedEnv) -> None:
    """The by-id route bound its user to ``_``, so any caller could read an action's
    full schema and custom headers. It must answer exactly like the listing."""
    connected = _create_custom_tool(env.admin)
    unconnected = _create_custom_tool(env.admin)
    PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
        tool_ids=[connected],
    )

    _assert_manager(env, "GET", f"/tool/{connected}", "allowed")
    _assert_manager(env, "GET", f"/tool/{unconnected}", "denied")


def test_manager_mcp_server_listing_isolates_unmanaged_groups(
    env: _ScopedEnv,
) -> None:
    """A server carries no group of its own, so the admin listing resolves reach the
    same way the tool listing does: owned, or connected to a managed group via an
    agent. This filter had no test at all."""
    own = _create_mcp_server(
        env.manager, is_public=False, groups=[env.managed_group.id]
    )
    foreign = _create_mcp_server(
        env.admin, is_public=False, groups=[env.other_group.id]
    )

    resp = _assert_manager(env, "GET", "/admin/mcp/servers", "allowed")
    listed = {server["id"] for server in resp.json()["mcp_servers"]}

    assert own in listed, "manager lost the server they own"
    assert foreign not in listed, "unmanaged group's server leaked"


def test_manager_agent_listing_isolates_unmanaged_groups(env: _ScopedEnv) -> None:
    """The admin list is a management surface, not a catalog: _admin_list_get_editable
    pins a scoped manager to the editable set, so a public agent they cannot edit is
    absent by design and an agent in an unmanaged group never appears."""
    mine = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.managed_group.id],
    )
    public = PersonaManager.create(user_performing_action=env.admin, is_public=True)
    foreign = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.other_group.id],
    )

    resp = _assert_manager(env, "GET", "/admin/persona", "allowed")
    listed = {persona["id"] for persona in resp.json()}

    assert mine.id in listed, "manager lost an agent shared to their group"
    assert public.id not in listed, "public agent is not manageable, so not listed"
    assert foreign.id not in listed, "unmanaged group's agent leaked"


def test_manager_cannot_read_agent_of_unmanaged_group(env: _ScopedEnv) -> None:
    """The by-id route must refuse what the listing hides."""
    foreign = PersonaManager.create(
        user_performing_action=env.admin,
        is_public=False,
        groups=[env.other_group.id],
    )
    resp = call_endpoint(
        "GET",
        f"/persona/{foreign.id}",
        None,
        env.manager.headers,
        env.manager.cookies,
    )
    # get_persona_by_id raises a bare ValueError, which the global handler renders as
    # 400 — the denial holds, the code just isn't the 403/404 the shape suggests
    assert resp.status_code in (400, 403, 404), resp.text
