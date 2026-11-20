"""Migration 730bce2814a0 copies each MCP server, external app and OpenAPI
custom tool into the integration tables, with its access and its agent and
task links. It makes no plugin. The rows are seeded at the revision before it,
then the chain upgrades."""

import ast
import base64
import hashlib
import importlib.util
import json
import sys
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from ee.onyx.utils.encryption import build_keyring, encrypt_with_keyring
from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.tools.models import ToolOptions
from onyx.utils.encryption import encrypt_string_to_bytes
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "ff11c4042c42"
REVISION = "730bce2814a0"
ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")

# Old tables the migration reads. Their rows must not change.
OLD_TABLES = (
    "gated_app",
    "external_app",
    "mcp_server",
    "mcp_server__user",
    "mcp_server__user_group",
    "mcp_server_user_preference",
    "tool",
    "tool_user_preference",
    "persona__tool",
    "persona__user",
    "persona__user_group",
    "workspace_action_policy",
    "external_app__skill",
    "user_action_policy",
    "scheduled_task_enabled_app",
    "scheduled_task_action_policy",
)

# The copy makes no plugin, so the rows of these tables must not change.
PLUGIN_TABLES = (
    "plugin_marketplace",
    "plugin",
    "plugin_version",
    "plugin__user",
    "plugin__user_group",
    "user_plugin_preference",
)

OPENAPI_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/issues": {
            "get": {"operationId": "listIssues", "summary": "List"},
            "post": {"operationId": "createIssue", "summary": "Create"},
        }
    },
}


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    _migrate("upgrade", "head")
    _migrate("downgrade", PREVIOUS_REVISION)
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        yield engine
    finally:
        _migrate("upgrade", "head")
        engine.dispose()


@dataclass
class Seeded:
    owner: UUID
    other: UUID
    admin: UUID
    inactive: UUID
    agent_user: UUID
    unlisted_user: UUID
    group: int
    agent_group: int
    agent_owner_group: int
    default_group: int
    persona: int
    own_persona: int
    bot_persona: int
    agent_personas: list[int]
    task: UUID
    mcp_public: int
    mcp_private: int
    mcp_user_key: int
    mcp_orphan: int
    mcp_agent_public: int
    mcp_agent_orphan: int
    app_slack: int
    app_custom: int
    app_org_key: int
    app_user_key: int
    tool_read: int
    tool_write: int
    tool_unselected: int
    tool_selected: int
    custom_private: int
    custom_shared: int
    custom_default: int
    custom_oauth: int
    custom_disabled: int
    custom_admin: int
    custom_public: int
    only_skill: UUID
    built_in_tool: int
    chat_session: UUID
    shared_skills: list[UUID]
    gated: dict[str, int]
    names: dict[str, str]


def _insert(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def _seed(conn: Connection) -> Seeded:
    s = uuid4().hex[:8]
    users: dict[str, UUID] = {}
    for key in ("owner", "other", "admin", "inactive", "agent_user", "unlisted_user"):
        users[key] = _insert(
            conn,
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true) "
            "RETURNING id",
            id=uuid4(),
            email=f"u1-{key}-{s}@example.com",
        )
    conn.execute(
        text('UPDATE "user" SET is_active = false WHERE id = :id'),
        {"id": users["inactive"]},
    )
    conn.execute(
        text(
            'UPDATE "user" SET effective_permissions = \'["admin"]\'::jsonb '
            "WHERE id = :id"
        ),
        {"id": users["admin"]},
    )
    group = _insert(
        conn,
        "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
        "VALUES (:name, true, false) RETURNING id",
        name=f"u1-group-{s}",
    )
    agent_group = _insert(
        conn,
        "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
        "VALUES (:name, true, false) RETURNING id",
        name=f"u1-agent-group-{s}",
    )
    # Stands in for Admin: a default group other than Basic.
    default_group = _insert(
        conn,
        "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion, "
        "is_default) VALUES (:name, true, false, true) RETURNING id",
        name=f"u1-default-{s}",
    )
    conn.execute(
        text(
            "INSERT INTO user__user_group (user_group_id, user_id) "
            "VALUES (:group, :user)"
        ),
        {"group": default_group, "user": users["admin"]},
    )

    def persona(
        owner: UUID, name: str, *, public: bool = False, listed: bool = True
    ) -> int:
        return _insert(
            conn,
            "INSERT INTO persona (name, description, deleted, is_listed, "
            "is_public, builtin_persona, user_id) VALUES "
            "(:name, '', false, :listed, :public, false, :owner) RETURNING id",
            name=f"u1-{name}-{s}",
            owner=owner,
            public=public,
            listed=listed,
        )

    other_persona = persona(users["other"], "persona")
    own_persona = persona(users["owner"], "own-persona")
    bot_persona = persona(users["owner"], "bot-persona")
    conn.execute(
        text(
            "INSERT INTO discord_guild_config (registration_key, default_persona_id) "
            "VALUES (:key, :persona)"
        ),
        {"key": f"u1-{s}", "persona": bot_persona},
    )

    def mcp(name: str, owner: str, public: bool, auth: str, performer: str) -> int:
        return _insert(
            conn,
            "INSERT INTO mcp_server (owner, name, server_url, transport, auth_type, "
            "auth_performer, is_public, oauth_authorization_endpoint, "
            "oauth_token_endpoint, last_refreshed_at, created_at, updated_at) VALUES "
            "(:owner, :name, :url, 'STREAMABLE_HTTP', :auth, :performer, :public, "
            "'https://auth.example.com/a', 'https://auth.example.com/t', "
            "TIMESTAMPTZ '2026-10-01 00:00:00+00', "
            "TIMESTAMPTZ '2026-09-01 00:00:00+00', "
            "TIMESTAMPTZ '2026-09-02 00:00:00+00') RETURNING id",
            owner=owner,
            name=name,
            url=f"https://{name}.example.com/mcp",
            auth=auth,
            performer=performer,
            public=public,
        )

    names = {
        "shared": f"u1-tracker-{s}",
        "private": f"u1-private-{s}",
        "orphan": f"u1-orphan-{s}",
        "user_key": f"u1-per-user-mcp-{s}",
        "agent_public": f"u1-agent-public-{s}",
        "agent_orphan": f"u1-agent-orphan-{s}",
    }
    owner_email = f"u1-owner-{s}@example.com"
    mcp_public = mcp(names["shared"], owner_email, True, "OAUTH", "PER_USER")
    mcp_private = mcp(names["private"], owner_email, False, "API_TOKEN", "ADMIN")
    mcp_orphan = mcp(names["orphan"], f"gone-{s}@example.com", False, "NONE", "ADMIN")
    mcp_user_key = mcp(names["user_key"], owner_email, False, "API_TOKEN", "PER_USER")
    # Private servers that only agents give to other people.
    mcp_agent_public = mcp(names["agent_public"], owner_email, False, "NONE", "ADMIN")
    mcp_agent_orphan = mcp(
        names["agent_orphan"], f"gone-{s}@example.com", False, "NONE", "ADMIN"
    )
    # Only the public server is available in Craft.
    conn.execute(
        text(
            "UPDATE mcp_server SET available_in_craft = (id = :public) "
            "WHERE id = ANY(:ids)"
        ),
        {"public": mcp_public, "ids": [mcp_public, mcp_private, mcp_orphan]},
    )
    conn.execute(
        text(
            "UPDATE mcp_server SET oauth_scopes_override = "
            'CAST(\'["repo", "read:org"]\' AS jsonb), '
            'oauth_additional_auth_params = CAST(\'{"prompt": "consent"}\' AS jsonb) '
            "WHERE id = :id"
        ),
        {"id": mcp_public},
    )

    def mcp_tool(server: int, name: str, read_only: bool, enabled: bool) -> int:
        return _insert(
            conn,
            "INSERT INTO tool (name, description, display_name, mcp_server_id, "
            "mcp_input_schema, mcp_read_only, enabled) VALUES (:name, 'd', :name, "
            ":server, CAST(:schema AS jsonb), :read_only, :enabled) RETURNING id",
            name=name,
            server=server,
            schema=json.dumps({"type": "object"}),
            read_only=read_only,
            enabled=enabled,
        )

    tool_read = mcp_tool(mcp_public, "list_issues", True, True)
    tool_write = mcp_tool(mcp_public, "create_issue", False, True)
    tool_unselected = mcp_tool(mcp_private, "drop_table", False, False)
    tool_selected = mcp_tool(mcp_private, "query", True, True)
    tool_agent_public = mcp_tool(mcp_agent_public, "search", True, True)
    tool_agent_orphan = mcp_tool(mcp_agent_orphan, "lookup", True, True)

    def app(name: str, app_type: str, template: dict[str, str]) -> int:
        return _insert(
            conn,
            "INSERT INTO external_app (name, app_type, organization_credentials, "
            "auth_template, upstream_url_patterns, created_at, updated_at) VALUES "
            "(:name, :app_type, '\\x00'::bytea, CAST(:template AS jsonb), "
            "ARRAY['https://slack.com/api/.*'], "
            "TIMESTAMPTZ '2026-08-01 00:00:00+00', "
            "TIMESTAMPTZ '2026-08-02 00:00:00+00') RETURNING id",
            name=name,
            app_type=app_type,
            template=json.dumps(template),
        )

    # Same name as the public MCP server: both go to the Organization library.
    app_slack = app(names["shared"], "SLACK", {"Authorization": "Bearer {token}"})
    app_custom = app(f"u1-custom-{s}", "CUSTOM", {})
    # The admin turned the custom app off. Each other app is on.
    conn.execute(
        text("UPDATE external_app SET enabled = (id <> :off) WHERE id = ANY(:ids)"),
        {"off": app_custom, "ids": [app_slack, app_custom]},
    )
    # The organization fills the key of one app. A user fills it for the other.
    app_org_key = app(f"u1-org-key-{s}", "CUSTOM", {"X-Key": "{api_key}"})
    app_user_key = app(f"u1-user-key-{s}", "CUSTOM", {"X-Key": "{api_key}"})
    conn.execute(
        text(
            "INSERT INTO external_app_user_credential (external_app_id, user_id, "
            "user_credentials, granted_scopes) VALUES "
            "(:a, :u, CAST(:secret AS bytea), ARRAY['read'])"
        ),
        {"a": app_user_key, "u": users["other"], "secret": b"user-key"},
    )
    # A credential of a deactivated user is not copied.
    conn.execute(
        text(
            "INSERT INTO external_app_user_credential (external_app_id, user_id, "
            "user_credentials) VALUES (:a, :u, '\\x00'::bytea)"
        ),
        {"a": app_user_key, "u": users["inactive"]},
    )

    def mcp_config(server: int | None, email: str, secret: bytes, day: int) -> int:
        return _insert(
            conn,
            "INSERT INTO mcp_connection_config (mcp_server_id, user_email, config, "
            "created_at, updated_at) VALUES (:server, :email, :secret, "
            "TIMESTAMPTZ '2026-10-01 00:00:00+00', "
            "TIMESTAMPTZ '2026-10-01 00:00:00+00' + make_interval(days => :day)) "
            "RETURNING id",
            server=server,
            email=email,
            secret=secret,
            day=day,
        )

    # A per-user API key server keeps its template in the admin config.
    user_key_template = encrypt_string_to_bytes(
        json.dumps(
            {
                "headers": {},
                "header_template": {
                    "X-Api-Key": "{api_key}",
                    "X-Team": "{team_id}",
                    "X-User": "{user_email}",
                    "Host": "{api_key}.internal",
                },
                "required_fields": ["api_key", "team_id"],
            }
        )
    )
    for server, secret in (
        (mcp_public, b"public-admin"),
        (mcp_private, b"private-admin"),
        (mcp_user_key, user_key_template),
    ):
        conn.execute(
            text("UPDATE mcp_server SET admin_connection_config_id = :c WHERE id = :s"),
            {"c": mcp_config(server, "", secret, 0), "s": server},
        )
    other_email = f"u1-other-{s}@example.com"
    # The newer of two configs of a user wins; the email matches in any case.
    mcp_config(mcp_public, other_email.upper(), b"other-old", 1)
    mcp_config(mcp_public, other_email, b"other-new", 2)
    # No active user has this email.
    mcp_config(mcp_public, f"u1-gone-{s}@example.com", b"gone", 3)
    mcp_config(mcp_user_key, other_email, b"other-key", 1)

    gated: dict[str, int] = {}
    for key, column, target in (
        ("mcp_public", "mcp_server_id", mcp_public),
        ("mcp_private", "mcp_server_id", mcp_private),
        ("mcp_orphan", "mcp_server_id", mcp_orphan),
        ("mcp_user_key", "mcp_server_id", mcp_user_key),
        ("mcp_agent_public", "mcp_server_id", mcp_agent_public),
        ("mcp_agent_orphan", "mcp_server_id", mcp_agent_orphan),
        ("app_custom", "external_app_id", app_custom),
    ):
        gated[key] = _insert(
            conn,
            f"INSERT INTO gated_app ({column}) VALUES (:target) RETURNING id",
            target=target,
        )
    gated["app_slack"] = _insert(
        conn,
        "INSERT INTO gated_app (external_app_id, users_can_manage_policies) "
        "VALUES (:target, false) RETURNING id",
        target=app_slack,
    )

    oauth_config = _insert(
        conn,
        "INSERT INTO oauth_config (name, authorization_url, token_url, client_id, "
        "client_secret, scopes, supports_pkce) VALUES (:name, "
        "'https://o.example.com/a', 'https://o.example.com/t', "
        "CAST(:client_id AS bytea), CAST(:client_secret AS bytea), "
        "CAST('[\"read\"]' AS jsonb), true) RETURNING id",
        client_id=b"oauth-client-id",
        client_secret=b"oauth-client-secret",
        name=f"u1-oauth-{s}",
    )

    def custom(
        name: str,
        headers: list[dict[str, str]] | None,
        oauth: int | None,
        enabled: bool = True,
        owner: str = "owner",
    ) -> int:
        return _insert(
            conn,
            "INSERT INTO tool (name, description, display_name, openapi_schema, "
            "custom_headers, user_id, passthrough_auth, oauth_config_id, enabled) "
            "VALUES (:name, 'd', :name, CAST(:schema AS jsonb), "
            "CAST(:headers AS jsonb), :owner, false, :oauth, :enabled) RETURNING id",
            name=name,
            schema=json.dumps(OPENAPI_SCHEMA),
            headers=json.dumps(headers) if headers is not None else None,
            owner=users[owner],
            oauth=oauth,
            enabled=enabled,
        )

    custom_private = custom(
        f"u1-custom-private-{s}", [{"key": "X-Key", "value": "secret"}], None
    )
    custom_shared = custom(f"u1-custom-shared-{s}", None, None)
    custom_default = custom(f"u1-custom-default-{s}", None, None)
    custom_oauth = custom(
        f"u1-custom-oauth-{s}",
        [
            {"key": "X-Team", "value": "platform"},
            {"key": "X-Literal", "value": "a{b}c"},
        ],
        oauth_config,
    )
    for user_key, secret in (("other", b"oauth-token"), ("inactive", b"gone")):
        conn.execute(
            text(
                "INSERT INTO oauth_user_token (oauth_config_id, user_id, token_data) "
                "VALUES (:o, :u, :secret)"
            ),
            {"o": oauth_config, "u": users[user_key], "secret": secret},
        )
    # Turned off for the default agent; a custom agent still has it.
    custom_disabled = custom(f"u1-custom-disabled-{s}", None, None, enabled=False)
    custom_admin = custom(f"u1-custom-admin-{s}", None, None, owner="admin")
    custom_public = custom(f"u1-custom-public-{s}", None, None)

    # The agents that give a private server to their users.
    shared_persona = persona(users["other"], "shared-persona")
    for user_key in ("agent_user",):
        conn.execute(
            text("INSERT INTO persona__user (persona_id, user_id) VALUES (:p, :u)"),
            {"p": shared_persona, "u": users[user_key]},
        )
    for group_id in (agent_group, default_group):
        conn.execute(
            text(
                "INSERT INTO persona__user_group (persona_id, user_group_id) "
                "VALUES (:p, :g)"
            ),
            {"p": shared_persona, "g": group_id},
        )
    # An agent that is not listed gives the server only to its owner.
    unlisted_persona = persona(users["other"], "unlisted-persona", listed=False)
    conn.execute(
        text("INSERT INTO persona__user (persona_id, user_id) VALUES (:p, :u)"),
        {"p": unlisted_persona, "u": users["unlisted_user"]},
    )
    # The owner group of an agent has it also when the agent is not listed.
    agent_owner_group = _insert(
        conn,
        "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
        "VALUES (:name, true, false) RETURNING id",
        name=f"u1-agent-owner-group-{s}",
    )
    group_persona = _insert(
        conn,
        "INSERT INTO persona (name, description, deleted, is_listed, "
        "is_public, builtin_persona, owner_group_id) VALUES "
        "(:name, '', false, false, false, false, :group) RETURNING id",
        name=f"u1-group-persona-{s}",
        group=agent_owner_group,
    )
    # An agent with only a tool that the admin did not select gives nothing.
    unselected_persona = persona(users["inactive"], "unselected-persona")
    public_persona = persona(users["other"], "public-persona", public=True)
    conn.execute(
        text("INSERT INTO persona__user (persona_id, user_id) VALUES (:p, :u)"),
        {"p": public_persona, "u": users["unlisted_user"]},
    )
    agent_personas = [
        shared_persona,
        unlisted_persona,
        group_persona,
        unselected_persona,
        public_persona,
    ]

    for persona_id, tool_id in (
        (shared_persona, tool_selected),
        (shared_persona, tool_agent_orphan),
        (unlisted_persona, tool_selected),
        (group_persona, tool_selected),
        (unselected_persona, tool_unselected),
        (public_persona, tool_agent_public),
        (public_persona, custom_public),
        (other_persona, tool_read),
        (other_persona, custom_shared),
        (own_persona, custom_private),
        (own_persona, tool_read),
        (own_persona, tool_write),
        (own_persona, tool_selected),
        (own_persona, tool_unselected),
        (bot_persona, tool_write),
        (bot_persona, custom_oauth),
        (0, tool_selected),
        (0, custom_default),
        (0, custom_disabled),
        # Default Chat has the private server with no owner.
        (0, tool_agent_orphan),
        (own_persona, custom_disabled),
    ):
        conn.execute(
            text("INSERT INTO persona__tool (persona_id, tool_id) VALUES (:p, :t)"),
            {"p": persona_id, "t": tool_id},
        )

    for server in (mcp_private, mcp_agent_orphan):
        conn.execute(
            text(
                "INSERT INTO mcp_server__user (mcp_server_id, user_id) VALUES (:s, :u)"
            ),
            {"s": server, "u": users["other"]},
        )
    for group_id in (group, default_group):
        conn.execute(
            text(
                "INSERT INTO mcp_server__user_group (mcp_server_id, user_group_id) "
                "VALUES (:s, :g)"
            ),
            {"s": mcp_private, "g": group_id},
        )

    for gated_app_id, action, policy in (
        (gated["mcp_public"], "create_issue", "ASK"),
        (gated["mcp_public"], "list_issues", "ALWAYS"),
        (gated["mcp_private"], "drop_table", "ALWAYS"),
        (gated["mcp_private"], "query", "ALWAYS"),
        (gated["app_slack"], "slack.messages.write", "DENY"),
    ):
        conn.execute(
            text(
                "INSERT INTO workspace_action_policy (gated_app_id, action_id, "
                "policy, created_at, updated_at) VALUES (:g, :a, :p, "
                "TIMESTAMPTZ '2026-10-05 00:00:00+00', "
                "TIMESTAMPTZ '2026-10-06 00:00:00+00')"
            ),
            {"g": gated_app_id, "a": action, "p": policy},
        )
    conn.execute(
        text(
            "INSERT INTO user_action_policy (user_id, gated_app_id, action_id, policy) "
            "VALUES (:u, :g, 'list_issues', 'ALWAYS')"
        ),
        {"u": users["other"], "g": gated["mcp_public"]},
    )

    conn.execute(
        text(
            "INSERT INTO mcp_server_user_preference (user_id, mcp_server_id, "
            "enabled_in_chat, enabled_in_craft) VALUES (:u, :s, false, true)"
        ),
        {"u": users["other"], "s": mcp_public},
    )
    conn.execute(
        text(
            "INSERT INTO tool_user_preference (user_id, tool_id, enabled_in_chat) "
            "VALUES (:u, :t, false)"
        ),
        {"u": users["other"], "t": custom_default},
    )
    conn.execute(
        text(
            "INSERT INTO mcp_server_user_preference (user_id, mcp_server_id, "
            "enabled_in_chat, enabled_in_craft) VALUES (:u, :s, false, false)"
        ),
        {"u": users["other"], "s": mcp_private},
    )
    # The user turned off every tool the agent has of the public server, and
    # one of the two tools on the own agent.
    for persona_id, user_id, disabled in (
        (other_persona, users["other"], [tool_read]),
        (own_persona, users["owner"], [tool_write]),
    ):
        conn.execute(
            text(
                "INSERT INTO assistant__user_specific_config (assistant_id, user_id, "
                "disabled_tool_ids) VALUES (:p, :u, :d)"
            ),
            {"p": persona_id, "u": user_id, "d": disabled},
        )

    task = _insert(
        conn,
        "INSERT INTO scheduled_task (id, user_id, name, prompt, cron_expression, "
        "editor_mode) VALUES (:id, :u, 'u1', 'p', '0 9 * * *', 'advanced') "
        "RETURNING id",
        id=uuid4(),
        u=users["owner"],
    )
    conn.execute(
        text(
            "INSERT INTO scheduled_task_enabled_app (scheduled_task_id, gated_app_id) "
            "VALUES (:t, :g)"
        ),
        {"t": task, "g": gated["app_slack"]},
    )
    conn.execute(
        text(
            "INSERT INTO scheduled_task_action_policy (scheduled_task_id, "
            "gated_app_id, action_id, policy) VALUES "
            "(:t, :g, 'slack.messages.write', 'ALWAYS')"
        ),
        {"t": task, "g": gated["app_slack"]},
    )

    session_id = _insert(
        conn,
        "INSERT INTO build_session (id, user_id) VALUES (:id, :u) RETURNING id",
        id=uuid4(),
        u=users["owner"],
    )
    conn.execute(
        text(
            "INSERT INTO action_approval (approval_id, session_id, payload, actions, "
            "app_name, gated_app_id) VALUES (:id, :s, '{}', '[]', 'slack', :g)"
        ),
        {"id": uuid4(), "s": session_id, "g": gated["app_slack"]},
    )
    built_in_tool = _insert(
        conn,
        "INSERT INTO tool (name, in_code_tool_id, enabled) "
        "VALUES (:name, :name, true) RETURNING id",
        name=f"u1-built-in-{s}",
    )
    chat_session_id = _insert(
        conn,
        "INSERT INTO chat_session (id, user_id, deleted, shared_status, "
        "onyxbot_flow, tool_selection) VALUES (:id, :u, false, 'PRIVATE', false, "
        "CAST(:selection AS jsonb)) RETURNING id",
        id=uuid4(),
        u=users["owner"],
        # A deleted tool id is left out.
        selection=json.dumps(
            {
                "allowed_tool_ids": [
                    built_in_tool,
                    tool_read,
                    custom_shared,
                    2_000_000_000,
                ],
                "preferred_tool_id": tool_read,
                "internal_search_filters": {"source_type": ["web"]},
            }
        ),
    )
    chat_message_id = _insert(
        conn,
        "INSERT INTO chat_message (chat_session_id, message, message_type, "
        "token_count) VALUES (:s, 'q', 'ASSISTANT', 1) RETURNING id",
        s=chat_session_id,
    )
    conn.execute(
        text(
            "INSERT INTO approval_request (id, chat_session_id, chat_message_id, "
            "gated_app_id, action_id, tool_call_id, tool_name, display_name, "
            "arguments) VALUES (:id, :s, :m, :g, 'create_issue', 'call_1', "
            "'create_issue', 'Create issue', '{}')"
        ),
        {
            "id": uuid4(),
            "s": chat_session_id,
            "m": chat_message_id,
            "g": gated["mcp_public"],
        },
    )
    conn.execute(
        text(
            "INSERT INTO action_receipt (id, session_id, action_type, effect, "
            "destination, gated_app_id) VALUES "
            "(:id, :s, 'slack.messages.write', 'write', 'slack', :g)"
        ),
        {"id": uuid4(), "s": session_id, "g": gated["app_slack"]},
    )

    conn.execute(
        text(
            "INSERT INTO plugin_marketplace (id, kind, name, owner_user_id, "
            "default_installation_policy, created_at) VALUES (:id, "
            "'organization_library', 'Organization library', NULL, 'AVAILABLE', "
            "TIMESTAMPTZ '2026-11-11 00:00:00+00') ON CONFLICT DO NOTHING"
        ),
        {"id": ORGANIZATION_LIBRARY_ID},
    )

    def app_skill(external_app_id: int, name: str) -> UUID:
        """A published custom skill, with its plugin, that needs the app."""
        skill_id = uuid4()
        params = {"id": skill_id, "name": f"u1-{name}-{s}", "u": users["owner"]}
        conn.execute(
            text(
                "INSERT INTO skill (id, name, description, bundle_file_id, "
                "bundle_sha256, author_user_id, public_permission) VALUES "
                "(:id, :name, '', :file, :sha, :u, 'VIEWER')"
            ),
            {**params, "file": f"u1-{skill_id.hex}", "sha": "0" * 64},
        )
        conn.execute(
            text(
                "INSERT INTO plugin (id, name, description, marketplace_id, "
                "author_user_id, current_version_id, published_version_id) VALUES "
                "(:id, :name, '', :m, :u, :id, :id)"
            ),
            {**params, "m": ORGANIZATION_LIBRARY_ID},
        )
        conn.execute(
            text(
                "INSERT INTO plugin_version (id, plugin_id, version_number) "
                "VALUES (:id, :id, 1)"
            ),
            {"id": skill_id},
        )
        conn.execute(
            text(
                "INSERT INTO external_app__skill (external_app_id, skill_id) "
                "VALUES (:a, :s)"
            ),
            {"a": external_app_id, "s": skill_id},
        )
        return skill_id

    # One app has one custom skill. One app has two.
    only_skill = app_skill(app_user_key, "only")
    shared_skills = [app_skill(app_org_key, "one"), app_skill(app_org_key, "two")]

    return Seeded(
        owner=users["owner"],
        other=users["other"],
        admin=users["admin"],
        inactive=users["inactive"],
        agent_user=users["agent_user"],
        unlisted_user=users["unlisted_user"],
        group=group,
        agent_group=agent_group,
        agent_owner_group=agent_owner_group,
        default_group=default_group,
        persona=other_persona,
        own_persona=own_persona,
        bot_persona=bot_persona,
        agent_personas=agent_personas,
        task=task,
        mcp_public=mcp_public,
        mcp_private=mcp_private,
        mcp_orphan=mcp_orphan,
        mcp_user_key=mcp_user_key,
        mcp_agent_public=mcp_agent_public,
        mcp_agent_orphan=mcp_agent_orphan,
        app_slack=app_slack,
        app_custom=app_custom,
        app_org_key=app_org_key,
        app_user_key=app_user_key,
        tool_read=tool_read,
        tool_write=tool_write,
        tool_unselected=tool_unselected,
        tool_selected=tool_selected,
        custom_private=custom_private,
        custom_shared=custom_shared,
        custom_default=custom_default,
        custom_oauth=custom_oauth,
        custom_disabled=custom_disabled,
        custom_admin=custom_admin,
        custom_public=custom_public,
        only_skill=only_skill,
        built_in_tool=built_in_tool,
        chat_session=chat_session_id,
        shared_skills=shared_skills,
        gated=gated,
        names=names,
    )


def _cleanup(conn: Connection, seeded: Seeded) -> None:
    custom_tools = [
        seeded.custom_private,
        seeded.custom_shared,
        seeded.custom_default,
        seeded.custom_oauth,
        seeded.custom_disabled,
        seeded.custom_admin,
        seeded.custom_public,
    ]
    if conn.execute(text("SELECT to_regclass('integration')")).scalar_one():
        params = {
            "gated": list(seeded.gated.values()),
            "tools": custom_tools,
            "apps": [seeded.app_org_key, seeded.app_user_key],
        }
        seeded_integrations = (
            "SELECT id FROM integration WHERE id = ANY(:gated) "
            "OR tool_id = ANY(:tools) OR external_app_id = ANY(:apps)"
        )
        conn.execute(
            text(f"DELETE FROM integration WHERE id IN ({seeded_integrations})"),
            params,
        )
    skills = [seeded.only_skill, *seeded.shared_skills]
    conn.execute(text("DELETE FROM plugin WHERE id = ANY(:ids)"), {"ids": skills})
    conn.execute(text("DELETE FROM skill WHERE id = ANY(:ids)"), {"ids": skills})
    conn.execute(
        text("DELETE FROM persona__tool WHERE persona_id = 0 AND tool_id = ANY(:t)"),
        {"t": [seeded.custom_default, seeded.custom_disabled, seeded.tool_selected]},
    )
    conn.execute(
        text("DELETE FROM mcp_server__user_group WHERE mcp_server_id = :s"),
        {"s": seeded.mcp_private},
    )
    conn.execute(
        text("DELETE FROM build_session WHERE user_id = :u"), {"u": seeded.owner}
    )
    conn.execute(
        text("DELETE FROM chat_session WHERE user_id = :u"), {"u": seeded.owner}
    )
    conn.execute(
        text("DELETE FROM discord_guild_config WHERE default_persona_id = :p"),
        {"p": seeded.bot_persona},
    )
    conn.execute(
        text("DELETE FROM tool WHERE id = ANY(:ids)"),
        {"ids": [*custom_tools, seeded.built_in_tool]},
    )
    servers = [
        seeded.mcp_public,
        seeded.mcp_private,
        seeded.mcp_orphan,
        seeded.mcp_user_key,
        seeded.mcp_agent_public,
        seeded.mcp_agent_orphan,
    ]
    conn.execute(
        text(
            "UPDATE mcp_server SET admin_connection_config_id = NULL "
            "WHERE id = ANY(:ids)"
        ),
        {"ids": servers},
    )
    conn.execute(
        text("DELETE FROM mcp_connection_config WHERE mcp_server_id = ANY(:ids)"),
        {"ids": servers},
    )
    conn.execute(
        text("DELETE FROM oauth_user_token WHERE user_id = ANY(:ids)"),
        {"ids": [seeded.other, seeded.inactive]},
    )
    conn.execute(
        text("DELETE FROM mcp_server WHERE id = ANY(:ids)"),
        {"ids": servers},
    )
    conn.execute(
        text("DELETE FROM external_app WHERE id = ANY(:ids)"),
        {
            "ids": [
                seeded.app_slack,
                seeded.app_custom,
                seeded.app_org_key,
                seeded.app_user_key,
            ]
        },
    )
    conn.execute(
        text("DELETE FROM oauth_config WHERE name LIKE 'u1-oauth-%'"),
    )
    personas = [
        seeded.persona,
        seeded.own_persona,
        seeded.bot_persona,
        *seeded.agent_personas,
    ]
    for table in ("persona__tool", "persona__user", "persona__user_group"):
        conn.execute(
            text(f"DELETE FROM {table} WHERE persona_id = ANY(:ids)"),
            {"ids": personas},
        )
    conn.execute(text("DELETE FROM persona WHERE id = ANY(:ids)"), {"ids": personas})
    conn.execute(
        text("DELETE FROM user__user_group WHERE user_group_id = :g"),
        {"g": seeded.default_group},
    )
    conn.execute(
        text('DELETE FROM "user" WHERE id = ANY(:ids)'),
        {
            "ids": [
                seeded.owner,
                seeded.other,
                seeded.admin,
                seeded.inactive,
                seeded.agent_user,
                seeded.unlisted_user,
            ]
        },
    )
    conn.execute(
        text("DELETE FROM user_group WHERE id = ANY(:ids)"),
        {
            "ids": [
                seeded.group,
                seeded.agent_group,
                seeded.agent_owner_group,
                seeded.default_group,
            ]
        },
    )


def _fingerprint(
    engine: Engine, tables: tuple[str, ...], ignore: str | None = None
) -> dict[str, str]:
    """md5 of every row of each table, in a stable order, without the column
    ``ignore``."""
    row = "(to_jsonb(t) - :ignore)::text" if ignore else "t::text"
    result: dict[str, str] = {}
    with engine.connect() as conn:
        for table in tables:
            rows = conn.execute(
                text(f"SELECT {row} AS r FROM {table} t ORDER BY r"),
                {"ignore": ignore} if ignore else {},
            ).scalars()
            result[table] = hashlib.md5("\n".join(rows).encode()).hexdigest()
    return result


@pytest.fixture(scope="module")
def seeded(engine: Engine) -> Generator[Seeded, None, None]:
    with engine.begin() as conn:
        data = _seed(conn)
    yield data
    with engine.begin() as conn:
        _cleanup(conn, data)


@dataclass
class Copied:
    id: int
    kind: str
    name: str
    owner_user_id: UUID | None
    installation_policy: str
    auth_mode: str
    auth_method: str | None
    header_template: dict[str, str] | None
    credential_fields: list[dict[str, Any]] | None
    users_can_save_always_allow: bool


def _copied(conn: Connection, where: str, **params: Any) -> Copied:
    row = conn.execute(
        text(
            "SELECT i.id, i.kind, i.name, i.owner_user_id, i.installation_policy, "
            "i.auth_mode, i.auth_method, i.header_template, i.credential_fields, "
            f"i.users_can_save_always_allow FROM integration i WHERE {where}"
        ),
        params,
    ).one()
    return Copied(**row._asdict())


TOOL_INTEGRATION = "i.tool_id = :t"


def _has_tool_selection(conn: Connection) -> bool:
    return conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'chat_session' AND column_name = 'tool_selection')"
        )
    ).scalar_one()


def _kind_integration(conn: Connection, table: str, row_id: int) -> int | None:
    """The integration that points at this row of a kind table."""
    return conn.execute(
        text(f"SELECT id FROM integration WHERE {table}_id = :id"), {"id": row_id}
    ).scalar_one_or_none()


def _actions(conn: Connection, integration_id: int) -> list[dict[str, Any]]:
    return [
        dict(row._mapping)
        for row in conn.execute(
            text(
                "SELECT key, source, display_name, description, read_only, "
                "default_policy, input_schema, output_schema, "
                "http_method, path_template FROM integration_action "
                "WHERE integration_id = :id ORDER BY key"
            ),
            {"id": integration_id},
        )
    ]


def _oauth_client(conn: Connection, integration_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT provider_mode, authorization_url, token_url, scopes, "
            "additional_params, pkce, cimd_enabled, client_id, client_secret, "
            "registration, legacy_format FROM integration_oauth_client "
            "WHERE integration_id = :id"
        ),
        {"id": integration_id},
    ).one_or_none()
    if row is None:
        return None
    return {
        key: bytes(value) if isinstance(value, memoryview) else value
        for key, value in row._mapping.items()
    }


def _connections(conn: Connection, integration_id: int) -> dict[Any, Any]:
    """Each connection by user (None: the organization), as (secret, tag,
    granted scopes)."""
    return {
        row.user_id: (bytes(row.secret), row.legacy_format, row.granted_scopes)
        for row in conn.execute(
            text(
                "SELECT user_id, secret, legacy_format, granted_scopes "
                "FROM integration_connection WHERE integration_id = :id"
            ),
            {"id": integration_id},
        )
    }


def _integration_shares(
    conn: Connection, table: str, column: str, integration_id: int
) -> set[Any]:
    """The users or groups that an integration is shared with, as viewers."""
    return set(
        conn.execute(
            text(
                f"SELECT {column} FROM {table} "
                "WHERE integration_id = :i AND permission = 'VIEWER'"
            ),
            {"i": integration_id},
        ).scalars()
    )


def _settings(
    conn: Connection, table: str, key: str, owner: Any, integration_id: int
) -> Any:
    """The action settings of an agent or task link. None: no link."""
    return conn.execute(
        text(
            f"SELECT action_settings FROM {table} "
            f"WHERE {key} = :o AND integration_id = :i"
        ),
        {"o": owner, "i": integration_id},
    ).scalar_one_or_none()


def test_copies_each_integration(engine: Engine, seeded: Seeded) -> None:
    before = _fingerprint(engine, OLD_TABLES)
    plugins_before = _fingerprint(engine, PLUGIN_TABLES)
    with engine.connect() as conn:
        max_gated = conn.execute(text("SELECT max(id) FROM gated_app")).scalar_one()

    _migrate("upgrade", REVISION)

    assert _fingerprint(engine, OLD_TABLES) == before
    with engine.connect() as conn:
        public = _copied(conn, "i.id = :id", id=seeded.gated["mcp_public"])
        private = _copied(conn, "i.id = :id", id=seeded.gated["mcp_private"])
        orphan = _copied(conn, "i.id = :id", id=seeded.gated["mcp_orphan"])
        per_user_mcp = _copied(conn, "i.id = :id", id=seeded.gated["mcp_user_key"])
        slack = _copied(conn, "i.id = :id", id=seeded.gated["app_slack"])
        app_custom = _copied(conn, "i.id = :id", id=seeded.gated["app_custom"])
        tool_ids = {
            "private": seeded.custom_private,
            "shared": seeded.custom_shared,
            "default": seeded.custom_default,
            "oauth": seeded.custom_oauth,
            "disabled": seeded.custom_disabled,
            "admin": seeded.custom_admin,
            "public": seeded.custom_public,
        }
        custom = {
            key: _copied(conn, TOOL_INTEGRATION, t=tool_id)
            for key, tool_id in tool_ids.items()
        }

        # Ids: a gated_app keeps its id; a custom tool takes the next id.
        assert sorted(c.id for c in custom.values()) == [
            custom[key].id for key in sorted(custom, key=lambda k: tool_ids[k])
        ]
        assert min(c.id for c in custom.values()) > max_gated
        next_id = conn.execute(
            text("SELECT nextval(pg_get_serial_sequence('integration', 'id'))")
        ).scalar_one()
        assert next_id > max(c.id for c in custom.values())

        # The copy makes no plugin and no marketplace, and the schema has
        # no table or column that names an integration by a plugin.
        assert _fingerprint(engine, PLUGIN_TABLES) == plugins_before
        for table in (
            "plugin__integration",
            "persona__plugin",
            "scheduled_task__plugin",
        ):
            assert (
                conn.execute(text(f"SELECT to_regclass('{table}')")).scalar_one()
                is None
            )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND column_name = 'disabled_plugin_ids'"
                )
            ).scalar_one()
            == 0
        )
        assert slack.name == public.name == seeded.names["shared"]

        # Each kind table points at its integration.
        for table, row_id, copied in (
            ("mcp_server", seeded.mcp_public, public),
            ("mcp_server", seeded.mcp_private, private),
            ("mcp_server", seeded.mcp_orphan, orphan),
            ("external_app", seeded.app_slack, slack),
            ("external_app", seeded.app_custom, app_custom),
        ):
            assert _kind_integration(conn, table, row_id) == copied.id
        for tool_id in (
            seeded.tool_read,
            seeded.tool_write,
            seeded.tool_unselected,
            seeded.tool_selected,
        ):
            assert _kind_integration(conn, "tool", tool_id) is None

        # Kind, actions and sign-in settings, with no secret.
        assert public.kind == "mcp"
        assert (public.auth_mode, public.auth_method) == ("individual", "oauth2")
        assert _oauth_client(conn, public.id) == {
            "provider_mode": "discovery",
            "authorization_url": "https://auth.example.com/a",
            "token_url": "https://auth.example.com/t",
            "scopes": ["repo", "read:org"],
            "additional_params": {"prompt": "consent"},
            "pkce": True,
            "cimd_enabled": True,
            "client_id": None,
            "client_secret": None,
            # The OAuth client of an MCP server is in its admin configuration.
            "registration": b"public-admin",
            "legacy_format": "mcp_config",
        }
        mcp_action = {
            "source": "mcp",
            "description": "d",
            "default_policy": None,
            "input_schema": {"type": "object"},
            "output_schema": None,
            "http_method": None,
            "path_template": None,
        }
        assert _actions(conn, public.id) == [
            {
                **mcp_action,
                "key": "create_issue",
                "display_name": "create_issue",
                "read_only": False,
            },
            {
                **mcp_action,
                "key": "list_issues",
                "display_name": "list_issues",
                "read_only": True,
            },
        ]
        assert [a["key"] for a in _actions(conn, private.id)] == [
            "drop_table",
            "query",
        ]
        assert (private.auth_mode, private.auth_method) == ("shared", "api_key")
        assert _oauth_client(conn, private.id) is None
        assert (orphan.auth_mode, orphan.auth_method) == ("none", None)
        assert _actions(conn, orphan.id) == []
        assert slack.kind == "api"
        assert (slack.auth_mode, slack.auth_method) == ("individual", "oauth2")
        assert _oauth_client(conn, slack.id) == {
            "provider_mode": "preset",
            "authorization_url": None,
            "token_url": None,
            "scopes": None,
            "additional_params": None,
            "pkce": None,
            "cimd_enabled": False,
            "client_id": None,
            "client_secret": None,
            "registration": b"\x00",
            "legacy_format": "external_app_org",
        }
        # The actions of a catalog or a spec are written on first read.
        assert _actions(conn, slack.id) == []
        assert slack.header_template == {"Authorization": "Bearer {token}"}
        assert not slack.users_can_save_always_allow
        assert app_custom.kind == "api"
        assert (app_custom.auth_mode, app_custom.auth_method) == ("none", None)
        assert _oauth_client(conn, app_custom.id) is None
        assert _actions(conn, app_custom.id) == []
        # A custom app with a header template: a saved user credential shows
        # that each user signs in. With none, the organization holds the key.
        app_integration = "i.external_app_id = :a"
        org_key = _copied(conn, app_integration, a=seeded.app_org_key)
        user_key = _copied(conn, app_integration, a=seeded.app_user_key)
        assert (org_key.auth_mode, org_key.auth_method) == ("shared", "api_key")
        assert (user_key.auth_mode, user_key.auth_method) == ("individual", "api_key")
        assert custom["private"].kind == "api"
        assert _actions(conn, custom["private"].id) == []
        assert (custom["private"].auth_mode, custom["private"].auth_method) == (
            "shared",
            "api_key",
        )
        assert _oauth_client(conn, custom["private"].id) is None
        assert (custom["oauth"].auth_mode, custom["oauth"].auth_method) == (
            "individual",
            "oauth2",
        )
        assert _oauth_client(conn, custom["oauth"].id) == {
            "provider_mode": "manual",
            "authorization_url": "https://o.example.com/a",
            "token_url": "https://o.example.com/t",
            "scopes": ["read"],
            "additional_params": None,
            "pkce": True,
            "cimd_enabled": False,
            # The bytes of oauth_config, in the same encrypted string format.
            "client_id": b"oauth-client-id",
            "client_secret": b"oauth-client-secret",
            "registration": None,
            "legacy_format": None,
        }

        # Credentials: each secret is copied as its bytes, with its old format.
        # A user who is not active, or an email that no active user has, gets
        # no connection.
        assert _connections(conn, public.id) == {
            None: (b"public-admin", "mcp_config", None),
            seeded.other: (b"other-new", "mcp_config", None),
        }
        assert _connections(conn, private.id) == {
            None: (b"private-admin", "mcp_config", None),
        }

        # A per-user API key server: the template of its encrypted admin
        # config, with no denylisted header, and a field for each placeholder
        # that a user fills.
        assert (per_user_mcp.auth_mode, per_user_mcp.auth_method) == (
            "individual",
            "api_key",
        )
        assert per_user_mcp.header_template == {
            "X-Api-Key": "{api_key}",
            "X-Team": "{team_id}",
            "X-User": "{user_email}",
        }
        assert per_user_mcp.credential_fields == [
            {"key": "api_key", "label": "api key", "secret": True},
            {"key": "team_id", "label": "team id", "secret": True},
        ]
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM integration_action a "
                    "JOIN integration i ON i.id = a.integration_id "
                    "WHERE i.kind = 'api'"
                )
            ).scalar_one()
            == 0
        )
        user_key_admin = conn.execute(
            text(
                "SELECT c.config FROM mcp_connection_config c JOIN mcp_server m "
                "ON m.admin_connection_config_id = c.id WHERE m.id = :id"
            ),
            {"id": seeded.mcp_user_key},
        ).scalar_one()
        assert _connections(conn, per_user_mcp.id) == {
            None: (bytes(user_key_admin), "mcp_config", None),
            seeded.other: (b"other-key", "mcp_config", None),
        }
        assert _connections(conn, org_key.id) == {
            None: (b"\x00", "external_app_org", None),
        }
        assert _connections(conn, user_key.id) == {
            None: (b"\x00", "external_app_org", None),
            seeded.other: (b"user-key", "external_app_user", ["read"]),
        }
        assert _connections(conn, slack.id) == {}
        assert _connections(conn, app_custom.id) == {}
        assert _connections(conn, custom["oauth"].id) == {
            seeded.other: (b"oauth-token", "oauth_user_token", None),
        }
        # The plain headers of a shared OpenAPI tool, as plain UTF-8 bytes.
        headers = _connections(conn, custom["private"].id)
        assert list(headers) == [None]
        assert json.loads(headers[None][0]) == [{"key": "X-Key", "value": "secret"}]
        assert headers[None][1] == "tool_headers"
        # Static headers of an OpenAPI tool that signs in with OAuth become
        # literal values of the header template, with each brace doubled.
        assert custom["oauth"].header_template == {
            "X-Team": "platform",
            "X-Literal": "a{{b}}c",
        }
        assert custom["oauth"].header_template["X-Literal"].format() == "a{b}c"
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM integration_connection "
                    "WHERE status <> 'connected' OR expires_at IS NOT NULL"
                )
            ).scalar_one()
            == 0
        )

        # Policies.
        policies = {
            (row.integration_id, row.action, row.user_id): row.policy
            for row in conn.execute(
                text(
                    "SELECT integration_id, action, user_id, policy "
                    "FROM integration_action_policy WHERE integration_id = ANY(:ids)"
                ),
                {"ids": list(seeded.gated.values())},
            )
        }
        assert policies == {
            (public.id, "create_issue", None): "ask",
            # Available in Craft: the admin Always allow stays an admin value.
            (public.id, "list_issues", None): "allow",
            # The admin did not select drop_table: blocked wins over its
            # saved Always allow.
            (private.id, "drop_table", None): "blocked",
            # Not available in Craft: the Always allow of "query" was set for
            # chat only, so it makes no admin value.
            (slack.id, "slack.messages.write", None): "blocked",
            (public.id, "list_issues", seeded.other): "allow",
        }
        # Each agent with "query" keeps it with no question. The tool that the
        # admin did not select gets no allow.
        assert _settings(
            conn, "persona__integration", "persona_id", seeded.own_persona, private.id
        ) == {
            "default": "blocked",
            "actions": {"query": "allow", "drop_table": "inherit"},
        }
        # Chat runs a custom tool with no question: the default row is allow.
        assert {
            (row.integration_id, row.action, row.user_id, row.policy)
            for row in conn.execute(
                text(
                    "SELECT integration_id, action, user_id, policy "
                    "FROM integration_action_policy WHERE integration_id = ANY(:ids)"
                ),
                {"ids": [c.id for c in custom.values()]},
            )
        } == {(c.id, "", None, "allow") for c in custom.values()}
        # The integration holds its own access. Its owner is the person who
        # set it up. An integration of the organization is Available, or what
        # its source gives. Each other integration is private.
        assert private.owner_user_id == seeded.owner
        assert public.owner_user_id == seeded.owner
        assert orphan.owner_user_id is None and slack.owner_user_id is None
        assert custom["private"].owner_user_id == seeded.owner
        assert {
            "public": public.installation_policy,
            "slack": slack.installation_policy,
            "app_custom": app_custom.installation_policy,
            "private": private.installation_policy,
            "orphan": orphan.installation_policy,
            **{f"custom_{key}": c.installation_policy for key, c in custom.items()},
        } == {
            "public": "AVAILABLE",
            # An enabled app was on for each user.
            "slack": "DEFAULT",
            "app_custom": "NOT_AVAILABLE",
            "private": "NOT_AVAILABLE",
            "orphan": "NOT_AVAILABLE",
            "custom_private": "NOT_AVAILABLE",
            # On an agent of other people: an agent gives no access.
            "custom_shared": "NOT_AVAILABLE",
            "custom_default": "DEFAULT",
            # Only an agent of its owner has it.
            "custom_oauth": "NOT_AVAILABLE",
            "custom_disabled": "NOT_AVAILABLE",
            # Each user had these: an admin made one, a public agent has one.
            "custom_admin": "AVAILABLE",
            "custom_public": "AVAILABLE",
        }
        # A private server keeps its own people. An agent gives no access, so
        # the users of its agents get no share. A default group becomes its
        # members.
        assert _integration_shares(
            conn, "integration__user", "user_id", private.id
        ) == {seeded.other, seeded.admin}
        assert _integration_shares(
            conn, "integration__user_group", "user_group_id", private.id
        ) == {seeded.group}
        # A server of a public agent stays private with no share: an agent
        # gives no access.
        agent_public = _copied(conn, "i.id = :id", id=seeded.gated["mcp_agent_public"])
        assert agent_public.installation_policy == "NOT_AVAILABLE"
        assert (
            _integration_shares(conn, "integration__user", "user_id", agent_public.id)
            == set()
        )
        # A private server with no owner keeps its admins.
        agent_orphan = _copied(conn, "i.id = :id", id=seeded.gated["mcp_agent_orphan"])
        assert agent_orphan.installation_policy == "NOT_AVAILABLE"
        admins = set(
            conn.execute(
                text(
                    'SELECT id FROM "user" '
                    "WHERE effective_permissions @> '[\"admin\"]'::jsonb"
                )
            ).scalars()
        )
        assert seeded.admin in admins
        assert _integration_shares(
            conn, "integration__user", "user_id", agent_orphan.id
        ) == admins | {seeded.other}
        # Default Chat had it, so it stays on for the share and the admins.
        assert {
            row.user_id
            for row in conn.execute(
                text(
                    "SELECT user_id FROM user_integration_preference "
                    "WHERE integration_id = :i AND enabled"
                ),
                {"i": agent_orphan.id},
            )
        } >= {seeded.other, seeded.admin}
        # No copied group row holds an install setting.
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM integration__user_group "
                    "WHERE installation_policy IS NOT NULL OR permission IS NULL"
                )
            ).scalar_one()
            == 0
        )
        # An integration that is not a private MCP server gets no share.
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM integration__user WHERE integration_id "
                    "= ANY(:ids)"
                ),
                {"ids": [public.id, slack.id, *(c.id for c in custom.values())]},
            ).scalar_one()
            == 0
        )

        # The old tool selection of a chat, as tool options.
        tool_options = conn.execute(
            text("SELECT tool_options FROM chat_session WHERE id = :id"),
            {"id": seeded.chat_session},
        ).scalar_one()
        assert tool_options == {
            "allowed": [
                {"type": "capability", "tool_id": seeded.built_in_tool},
                {
                    "type": "integration",
                    "integration_id": public.id,
                    "actions": ["list_issues"],
                },
                {"type": "integration", "integration_id": custom["shared"].id},
            ],
            "preferred": {
                "type": "action",
                "integration_id": public.id,
                "action": "list_issues",
            },
            "internal_search_filters": {"source_type": ["web"]},
        }
        # The app reads the stored value: its models forbid an unknown key.
        assert ToolOptions.model_validate(tool_options).allowed_integrations() == {
            public.id: frozenset({"list_issues"}),
            custom["shared"].id: None,
        }
        assert _has_tool_selection(conn) is False

        # Choices of users.
        assert {
            row.integration_id: (row.enabled, row.enabled_at)
            for row in conn.execute(
                text(
                    "SELECT integration_id, enabled, enabled_at "
                    "FROM user_integration_preference WHERE user_id = :u"
                ),
                {"u": seeded.other},
            )
        } == {
            public.id: (False, None),
            private.id: (False, None),
            custom["default"].id: (False, None),
            agent_orphan.id: (True, None),
        }
        assert {
            row.user_id: row.enabled
            for row in conn.execute(
                text(
                    "SELECT user_id, enabled FROM user_integration_preference "
                    "WHERE integration_id = :i"
                ),
                {"i": private.id},
            )
        } == {seeded.owner: True, seeded.admin: True, seeded.other: False}
        assert {
            row.assistant_id: row.disabled_integration_ids
            for row in conn.execute(
                text(
                    "SELECT assistant_id, disabled_integration_ids "
                    "FROM assistant__user_specific_config WHERE assistant_id = ANY(:p)"
                ),
                {"p": [seeded.persona, seeded.own_persona]},
            )
        } == {seeded.persona: [public.id], seeded.own_persona: []}

        # Agents keep the same actions and no other.
        assert _settings(
            conn, "persona__integration", "persona_id", seeded.persona, public.id
        ) == {"default": "blocked", "actions": {"list_issues": "inherit"}}
        assert _settings(
            conn, "persona__integration", "persona_id", seeded.own_persona, public.id
        ) == {
            "default": "blocked",
            "actions": {"list_issues": "inherit", "create_issue": "inherit"},
        }
        assert (
            _settings(
                conn,
                "persona__integration",
                "persona_id",
                seeded.persona,
                custom["shared"].id,
            )
            == {}
        )
        assert (
            _settings(
                conn,
                "persona__integration",
                "persona_id",
                seeded.persona,
                private.id,
            )
            is None
        )
        # The bot freeze.
        assert _settings(
            conn, "persona__integration", "persona_id", seeded.bot_persona, public.id
        ) == {"default": "blocked", "actions": {"create_issue": "allow"}}
        assert _settings(
            conn,
            "persona__integration",
            "persona_id",
            seeded.bot_persona,
            custom["oauth"].id,
        ) == {"default": "allow"}
        assert (
            _settings(
                conn, "persona__integration", "persona_id", 0, custom["default"].id
            )
            is not None
        )
        # The default agent leaves out a turned-off tool; a custom agent keeps it.
        # Its only other agent is its owner's own, so it stays private.
        assert custom["disabled"].installation_policy == "NOT_AVAILABLE"
        assert (
            _settings(
                conn, "persona__integration", "persona_id", 0, custom["disabled"].id
            )
            is None
        )
        assert (
            _settings(
                conn,
                "persona__integration",
                "persona_id",
                seeded.own_persona,
                custom["disabled"].id,
            )
            == {}
        )

        # A task keeps its pre-approvals, and each other action asks.
        assert _settings(
            conn,
            "scheduled_task__integration",
            "scheduled_task_id",
            seeded.task,
            slack.id,
        ) == {"default": "ask", "actions": {"slack.messages.write": "allow"}}

        for table in ("action_receipt", "action_approval"):
            assert (
                conn.execute(
                    text(f"SELECT integration_id FROM {table} WHERE gated_app_id = :g"),
                    {"g": seeded.gated["app_slack"]},
                ).scalar_one()
                == slack.id
            )
        assert (
            conn.execute(
                text(
                    "SELECT integration_id FROM approval_request "
                    "WHERE gated_app_id = :g"
                ),
                {"g": seeded.gated["mcp_public"]},
            ).scalar_one()
            == public.id
        )
        # Each record foreign key is validated after the copy commits.
        assert set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname LIKE 'fk_%_integration_id' AND convalidated"
                )
            ).scalars()
        ) >= {
            "fk_action_receipt_integration_id",
            "fk_action_approval_integration_id",
            "fk_approval_request_integration_id",
        }


def test_downgrade_then_upgrade_gives_the_same_rows(
    engine: Engine, seeded: Seeded
) -> None:
    _migrate("upgrade", REVISION)
    new_tables = (
        "integration",
        "integration_action",
        "integration_oauth_client",
        "integration_action_policy",
        "integration_connection",
        "integration__user",
        "integration__user_group",
        "user_integration_preference",
        "persona__integration",
        "scheduled_task__integration",
    )
    # The foreign keys that a delete of an integration, a user, a group, an
    # agent or a task follows.
    indexes = {
        "ix_integration_connection_integration_id",
        "ix_integration_action_policy_integration_id",
        "ix_integration_owner_user_id",
        "ix_integration__user_user_id",
        "ix_integration__user_group_user_group_id",
        "ix_user_integration_preference_integration_id",
        "ix_persona__integration_integration_id",
        "ix_scheduled_task__integration_integration_id",
        "uq_integration_action_policy_user_group",
    }
    with engine.connect() as conn:
        assert (
            set(
                conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE "
                        "schemaname = current_schema() AND indexname = ANY(:names)"
                    ),
                    {"names": sorted(indexes)},
                ).scalars()
            )
            == indexes
        )
    first = _fingerprint(engine, new_tables)
    old = _fingerprint(engine, OLD_TABLES)
    plugins = _fingerprint(engine, PLUGIN_TABLES)
    # An approval of an integration made after the upgrade has no gated_app.
    no_gated_app = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO approval_request (id, chat_session_id, chat_message_id, "
                "gated_app_id, integration_id, action_id, tool_call_id, tool_name, "
                "display_name, arguments) SELECT :id, chat_session_id, "
                "chat_message_id, NULL, integration_id, action_id, 'call_2', "
                "tool_name, display_name, arguments FROM approval_request "
                "WHERE gated_app_id = :g"
            ),
            {"id": no_gated_app, "g": seeded.gated["mcp_public"]},
        )

    _migrate("downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT to_regclass('integration')")).scalar_one() is None
        )
        assert _has_tool_selection(conn) is True
        for table in (
            "integration__user",
            "integration__user_group",
            "user_integration_preference",
            "persona__integration",
            "scheduled_task__integration",
        ):
            assert (
                conn.execute(text(f"SELECT to_regclass('{table}')")).scalar_one()
                is None
            )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'assistant__user_specific_config' "
                    "AND column_name = 'disabled_integration_ids'"
                )
            ).scalar_one()
            == 0
        )
        # The downgrade deletes it, then gated_app_id is required again.
        assert (
            conn.execute(
                text("SELECT count(*) FROM approval_request WHERE id = :id"),
                {"id": no_gated_app},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'approval_request' "
                    "AND column_name = 'gated_app_id'"
                )
            ).scalar_one()
            == "NO"
        )
    # The downgrade leaves each plugin, also the plugin of a skill.
    assert _fingerprint(engine, PLUGIN_TABLES) == plugins
    assert _fingerprint(engine, OLD_TABLES) == old

    _migrate("upgrade", REVISION)
    assert _fingerprint(engine, new_tables) == first


def test_each_integration_has_one_row_of_its_kind(
    engine: Engine, seeded: Seeded
) -> None:
    """The database ties each integration to exactly one row of its kind, and
    deleting that row deletes the integration."""
    _migrate("upgrade", "head")
    for row in (
        # No row of its kind.
        {"tool_id": None},
        # An MCP integration that points at a tool row.
        {"tool_id": seeded.tool_read},
    ):
        with engine.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO integration (kind, name, auth_mode, tool_id) "
                    "VALUES ('mcp', 'u1-no-kind-row', 'none', :tool_id)"
                ),
                row,
            )

    with engine.begin() as conn:
        # A delete of a skill plugin leaves the integration of its app.
        app_integration = _kind_integration(conn, "external_app", seeded.app_user_key)
        assert app_integration is not None
        conn.execute(
            text("DELETE FROM plugin WHERE id = :id"), {"id": seeded.only_skill}
        )
        assert (
            _kind_integration(conn, "external_app", seeded.app_user_key)
            == app_integration
        )

        integration_id = _kind_integration(conn, "mcp_server", seeded.mcp_orphan)
        assert integration_id is not None
        conn.execute(
            text("DELETE FROM mcp_server WHERE id = :id"), {"id": seeded.mcp_orphan}
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM integration WHERE id = :id"),
                {"id": integration_id},
            ).scalar_one()
            == 0
        )


def test_action_policy_row_has_one_scope(engine: Engine, seeded: Seeded) -> None:
    """A policy row is the admin value, the value of one group or the choice
    of one user. Each scope holds one row for each action."""
    _migrate("upgrade", "head")
    integration_id = seeded.gated["mcp_public"]
    insert = text(
        "INSERT INTO integration_action_policy "
        "(integration_id, action, user_id, user_group_id, policy) "
        "VALUES (:i, 'u1-scope', :u, :g, 'ask')"
    )

    def add(user: UUID | None, group: int | None) -> None:
        with engine.begin() as conn:
            conn.execute(insert, {"i": integration_id, "u": user, "g": group})

    try:
        add(None, None)
        add(None, seeded.group)
        add(None, seeded.agent_group)
        add(seeded.other, None)
        for user, group in (
            (None, None),
            (None, seeded.group),
            (seeded.other, None),
        ):
            with pytest.raises(IntegrityError):
                add(user, group)
        # A row cannot be for a user and for a group. A user with no row yet
        # keeps the unique indexes out of it.
        with pytest.raises(
            IntegrityError, match="ck_integration_action_policy_single_scope"
        ):
            add(seeded.admin, seeded.agent_group)
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM integration_action_policy WHERE action = 'u1-scope'")
            )


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[4]
        / "alembic"
        / "versions"
        / f"{REVISION}_add_integration_tables.py"
    )
    spec = importlib.util.spec_from_file_location("integration_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("legacy_secret", "write_key_id"),
    [
        ("", ""),
        ("a-legacy-secret-of-32-bytes-long!", ""),
        ("", "k1"),
        ("a-legacy-secret-of-32-bytes-long!", "legacy"),
    ],
    ids=["plain", "legacy-cbc", "envelope", "envelope-under-legacy-key"],
)
def test_migration_reads_each_ciphertext_format(
    monkeypatch: pytest.MonkeyPatch, legacy_secret: str, write_key_id: str
) -> None:
    """The frozen decrypt of the migration reads what the app encryption
    wrote before this revision, under the same settings."""
    keys_json = json.dumps({"k1": base64.b64encode(b"k" * 32).decode()})
    monkeypatch.setenv("ENCRYPTION_KEY_SECRET", legacy_secret)
    monkeypatch.setenv("ENCRYPTION_KEYS", keys_json)
    keyring = build_keyring(legacy_secret, keys_json, write_key_id)
    data = encrypt_with_keyring(keyring, '{"header_template": {"X": "{k}"}}')

    migration = _migration_module()
    legacy_key = migration._legacy_key()

    assert (
        migration._decrypt(data, migration._envelope_keys(legacy_key), legacy_key)
        == '{"header_template": {"X": "{k}"}}'
    )


def test_migration_imports_no_app_code() -> None:
    """A later move or rename in the app must not break the revision."""
    path = (
        Path(__file__).resolve().parents[4]
        / "alembic"
        / "versions"
        / f"{REVISION}_add_integration_tables.py"
    )
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                modules.add("." * node.level + (node.module or ""))
            else:
                modules.add(node.module)
    allowed_roots = sys.stdlib_module_names | {"alembic", "cryptography", "sqlalchemy"}
    assert sorted(m for m in modules if m.split(".")[0] not in allowed_roots) == []
