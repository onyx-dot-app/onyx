"""Migration 730bce2814a0 copies each MCP server, external app and OpenAPI
custom tool into the integration tables, with a home plugin for each. The
rows are seeded at the revision before it, then the chain upgrades."""

import hashlib
import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill, User
from onyx.db.plugin import (
    PluginAccessChange,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
    create_skill_plugin__no_commit,
    legacy_skill_version_content,
    publish_plugin__no_commit,
)
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "7c00f53ab75f"
REVISION = "730bce2814a0"
ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")

# Old tables the migration reads. Their rows must not change, except the new
# integration_id of each kind table.
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
    "workspace_action_policy",
    "external_app__skill",
    "user_action_policy",
    "scheduled_task_enabled_app",
    "scheduled_task_action_policy",
)

OPENAPI_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {"/issues": {"post": {"operationId": "createIssue", "summary": "Create"}}},
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
    group: int
    default_group: int
    persona: int
    own_persona: int
    bot_persona: int
    task: UUID
    mcp_public: int
    mcp_private: int
    mcp_orphan: int
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
    skill: UUID
    gated: dict[str, int]
    names: dict[str, str]


def _insert(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def _seed(conn: Connection) -> Seeded:
    s = uuid4().hex[:8]
    users: dict[str, UUID] = {}
    for key in ("owner", "other", "admin"):
        users[key] = _insert(
            conn,
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true) "
            "RETURNING id",
            id=uuid4(),
            email=f"u1-{key}-{s}@example.com",
        )
    group = _insert(
        conn,
        "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
        "VALUES (:name, true, false) RETURNING id",
        name=f"u1-group-{s}",
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

    def persona(owner: UUID, name: str) -> int:
        return _insert(
            conn,
            "INSERT INTO persona (name, description, deleted, is_listed, "
            "is_public, builtin_persona, user_id) VALUES "
            "(:name, '', false, true, false, false, :owner) RETURNING id",
            name=f"u1-{name}-{s}",
            owner=owner,
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
    }
    owner_email = f"u1-owner-{s}@example.com"
    mcp_public = mcp(names["shared"], owner_email, True, "OAUTH", "PER_USER")
    mcp_private = mcp(names["private"], owner_email, False, "API_TOKEN", "ADMIN")
    mcp_orphan = mcp(names["orphan"], f"gone-{s}@example.com", False, "NONE", "ADMIN")
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
    # The organization fills the key of one app. A user fills it for the other.
    app_org_key = app(f"u1-org-key-{s}", "CUSTOM", {"X-Key": "{api_key}"})
    app_user_key = app(f"u1-user-key-{s}", "CUSTOM", {"X-Key": "{api_key}"})
    conn.execute(
        text(
            "INSERT INTO external_app_user_credential (external_app_id, user_id, "
            "user_credentials) VALUES (:a, :u, '\\x00'::bytea)"
        ),
        {"a": app_user_key, "u": users["other"]},
    )

    gated: dict[str, int] = {}
    for key, column, target in (
        ("mcp_public", "mcp_server_id", mcp_public),
        ("mcp_private", "mcp_server_id", mcp_private),
        ("mcp_orphan", "mcp_server_id", mcp_orphan),
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
        "'https://o.example.com/a', 'https://o.example.com/t', '\\x00'::bytea, "
        "'\\x00'::bytea, CAST('[\"read\"]' AS jsonb), true) RETURNING id",
        name=f"u1-oauth-{s}",
    )

    def custom(
        name: str,
        headers: list[dict[str, str]] | None,
        oauth: int | None,
        enabled: bool = True,
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
            owner=users["owner"],
            oauth=oauth,
            enabled=enabled,
        )

    custom_private = custom(
        f"u1-custom-private-{s}", [{"key": "X-Key", "value": "secret"}], None
    )
    custom_shared = custom(f"u1-custom-shared-{s}", None, None)
    custom_default = custom(f"u1-custom-default-{s}", None, None)
    custom_oauth = custom(f"u1-custom-oauth-{s}", None, oauth_config)
    # Turned off for the default agent; a custom agent still has it.
    custom_disabled = custom(f"u1-custom-disabled-{s}", None, None, enabled=False)

    for persona_id, tool_id in (
        (other_persona, tool_read),
        (other_persona, custom_shared),
        (own_persona, custom_private),
        (own_persona, tool_read),
        (own_persona, tool_write),
        (own_persona, tool_selected),
        (own_persona, tool_unselected),
        (bot_persona, tool_write),
        (bot_persona, custom_oauth),
        (0, custom_default),
        (0, custom_disabled),
        (own_persona, custom_disabled),
    ):
        conn.execute(
            text("INSERT INTO persona__tool (persona_id, tool_id) VALUES (:p, :t)"),
            {"p": persona_id, "t": tool_id},
        )

    conn.execute(
        text("INSERT INTO mcp_server__user (mcp_server_id, user_id) VALUES (:s, :u)"),
        {"s": mcp_private, "u": users["other"]},
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
    chat_session_id = _insert(
        conn,
        "INSERT INTO chat_session (id, user_id, deleted, shared_status, "
        "onyxbot_flow) VALUES (:id, :u, false, 'PRIVATE', false) RETURNING id",
        id=uuid4(),
        u=users["owner"],
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

    # A published skill that needs the Slack app.
    skill = uuid4()
    conn.execute(
        text(
            "INSERT INTO plugin_marketplace (id, kind, name, owner_user_id, "
            "default_installation_policy, created_at) VALUES (:id, "
            "'organization_library', 'Organization library', NULL, 'AVAILABLE', "
            "TIMESTAMPTZ '2026-11-11 00:00:00+00') ON CONFLICT DO NOTHING"
        ),
        {"id": ORGANIZATION_LIBRARY_ID},
    )
    conn.execute(
        text(
            "INSERT INTO skill (id, name, description, bundle_file_id, "
            "bundle_sha256, author_user_id, public_permission) VALUES "
            "(:id, :name, '', :file, :sha, :u, 'VIEWER')"
        ),
        {
            "id": skill,
            "name": f"u1-skill-{s}",
            "file": f"u1-{skill.hex}",
            "sha": "0" * 64,
            "u": users["owner"],
        },
    )
    conn.execute(
        text(
            "INSERT INTO plugin (id, name, description, marketplace_id, "
            "author_user_id, current_version_id, published_version_id) VALUES "
            "(:id, :name, '', :m, :u, :id, :id)"
        ),
        {
            "id": skill,
            "name": f"u1-skill-{s}",
            "m": ORGANIZATION_LIBRARY_ID,
            "u": users["owner"],
        },
    )
    conn.execute(
        text(
            "INSERT INTO plugin_version (id, plugin_id, version_number) "
            "VALUES (:id, :id, 1)"
        ),
        {"id": skill},
    )
    conn.execute(
        text(
            "INSERT INTO external_app__skill (external_app_id, skill_id) "
            "VALUES (:a, :s)"
        ),
        {"a": app_slack, "s": skill},
    )

    return Seeded(
        owner=users["owner"],
        other=users["other"],
        admin=users["admin"],
        group=group,
        default_group=default_group,
        persona=other_persona,
        own_persona=own_persona,
        bot_persona=bot_persona,
        task=task,
        mcp_public=mcp_public,
        mcp_private=mcp_private,
        mcp_orphan=mcp_orphan,
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
        skill=skill,
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
    ]
    if conn.execute(text("SELECT to_regclass('integration')")).scalar_one():
        conn.execute(
            text(
                "DELETE FROM plugin WHERE id IN (SELECT plugin_id FROM integration "
                "WHERE id = ANY(:gated) OR id IN "
                "(SELECT integration_id FROM tool WHERE id = ANY(:tools)) OR id IN "
                "(SELECT integration_id FROM external_app WHERE id = ANY(:apps)))"
            ),
            {
                "gated": list(seeded.gated.values()),
                "tools": custom_tools,
                "apps": [seeded.app_org_key, seeded.app_user_key],
            },
        )
    conn.execute(text("DELETE FROM plugin WHERE id = :id"), {"id": seeded.skill})
    conn.execute(text("DELETE FROM skill WHERE id = :id"), {"id": seeded.skill})
    conn.execute(
        text("DELETE FROM persona__tool WHERE persona_id = 0 AND tool_id = ANY(:t)"),
        {"t": [seeded.custom_default, seeded.custom_disabled]},
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
    conn.execute(text("DELETE FROM tool WHERE id = ANY(:ids)"), {"ids": custom_tools})
    conn.execute(
        text("DELETE FROM mcp_server WHERE id = ANY(:ids)"),
        {"ids": [seeded.mcp_public, seeded.mcp_private, seeded.mcp_orphan]},
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
    personas = [seeded.persona, seeded.own_persona, seeded.bot_persona]
    conn.execute(
        text("DELETE FROM persona__tool WHERE persona_id = ANY(:ids)"),
        {"ids": personas},
    )
    conn.execute(text("DELETE FROM persona WHERE id = ANY(:ids)"), {"ids": personas})
    conn.execute(
        text("DELETE FROM user__user_group WHERE user_group_id = :g"),
        {"g": seeded.default_group},
    )
    conn.execute(
        text('DELETE FROM "user" WHERE id = ANY(:ids)'),
        {"ids": [seeded.owner, seeded.other, seeded.admin]},
    )
    conn.execute(
        text("DELETE FROM user_group WHERE id = ANY(:ids)"),
        {"ids": [seeded.group, seeded.default_group]},
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
    plugin_id: UUID
    plugin_name: str
    marketplace_id: UUID
    marketplace_kind: str
    author_user_id: UUID | None
    published: bool
    installation_policy: str | None
    auth_mode: str
    auth_method: str | None
    header_template: dict[str, str] | None
    users_can_save_always_allow: bool


def _copied(conn: Connection, where: str, **params: Any) -> Copied:
    row = conn.execute(
        text(
            "SELECT i.id, i.kind, i.name, i.plugin_id, p.name AS plugin_name, "
            "p.marketplace_id, m.kind AS marketplace_kind, p.author_user_id, "
            "p.published_version_id IS NOT NULL AS published, "
            "p.installation_policy, i.auth_mode, "
            "i.auth_method, i.header_template, "
            "i.users_can_save_always_allow "
            "FROM integration i JOIN plugin p ON p.id = i.plugin_id "
            f"JOIN plugin_marketplace m ON m.id = p.marketplace_id WHERE {where}"
        ),
        params,
    ).one()
    return Copied(**row._asdict())


TOOL_INTEGRATION = "i.id = (SELECT integration_id FROM tool WHERE id = :t)"


def _kind_integration(conn: Connection, table: str, row_id: int) -> int | None:
    return conn.execute(
        text(f"SELECT integration_id FROM {table} WHERE id = :id"), {"id": row_id}
    ).scalar_one()


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
            "registration FROM integration_oauth_client WHERE integration_id = :id"
        ),
        {"id": integration_id},
    ).one_or_none()
    return dict(row._mapping) if row else None


def _settings(conn: Connection, table: str, key: str, owner: Any, plugin: UUID) -> Any:
    return conn.execute(
        text(
            f"SELECT action_settings FROM {table} WHERE {key} = :o AND plugin_id = :p"
        ),
        {"o": owner, "p": plugin},
    ).scalar_one_or_none()


def test_copies_each_integration(engine: Engine, seeded: Seeded) -> None:
    before = _fingerprint(engine, OLD_TABLES, ignore="integration_id")
    with engine.connect() as conn:
        max_gated = conn.execute(text("SELECT max(id) FROM gated_app")).scalar_one()

    _migrate("upgrade", REVISION)

    assert _fingerprint(engine, OLD_TABLES, ignore="integration_id") == before
    with engine.connect() as conn:
        public = _copied(conn, "i.id = :id", id=seeded.gated["mcp_public"])
        private = _copied(conn, "i.id = :id", id=seeded.gated["mcp_private"])
        orphan = _copied(conn, "i.id = :id", id=seeded.gated["mcp_orphan"])
        slack = _copied(conn, "i.id = :id", id=seeded.gated["app_slack"])
        app_custom = _copied(conn, "i.id = :id", id=seeded.gated["app_custom"])
        tool_ids = {
            "private": seeded.custom_private,
            "shared": seeded.custom_shared,
            "default": seeded.custom_default,
            "oauth": seeded.custom_oauth,
            "disabled": seeded.custom_disabled,
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

        # Each home plugin has one version with no bundle and no skill.
        for copied in (public, private, orphan, slack, app_custom, *custom.values()):
            version = conn.execute(
                text(
                    "SELECT v.version_number, v.bundle_file_id, "
                    "(SELECT count(*) FROM plugin_skill s "
                    " WHERE s.plugin_version_id = v.id) AS skills "
                    "FROM plugin p JOIN plugin_version v "
                    "ON v.id = p.current_version_id AND v.plugin_id = p.id "
                    "WHERE p.id = :id"
                ),
                {"id": copied.plugin_id},
            ).one()
            assert (version.version_number, version.bundle_file_id) == (1, None)
            assert version.skills == 0
            assert (
                conn.execute(
                    text("SELECT count(*) FROM skill WHERE id = :id"),
                    {"id": copied.plugin_id},
                ).scalar_one()
                == 0
            )

        # Placement.
        assert public.marketplace_id == ORGANIZATION_LIBRARY_ID and public.published
        assert slack.marketplace_kind == "organization_library" and slack.published
        assert slack.installation_policy == "NOT_AVAILABLE"
        assert app_custom.installation_policy == "NOT_AVAILABLE"
        assert {public.plugin_name, slack.plugin_name} == {
            seeded.names["shared"],
            f"{seeded.names['shared']}-2",
        }
        assert slack.name == seeded.names["shared"]
        assert private.marketplace_kind == "user_uploads"
        assert private.author_user_id == seeded.owner and not private.published
        assert orphan.marketplace_kind == "organization_library"
        assert orphan.installation_policy == "NOT_AVAILABLE" and orphan.published
        assert custom["private"].marketplace_kind == "user_uploads"
        assert custom["shared"].marketplace_kind == "organization_library"
        assert custom["default"].marketplace_kind == "organization_library"
        assert custom["default"].installation_policy == "DEFAULT"
        assert custom["shared"].installation_policy is None
        assert custom["private"].author_user_id == seeded.owner

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
        assert public.kind == "mcp_server"
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
            "registration": None,
        }
        mcp_action = {
            "source": "mcp_sync",
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
            "registration": None,
        }
        # The provider catalog is code; the U3 sync writes its actions.
        assert _actions(conn, slack.id) == []
        assert slack.header_template == {"Authorization": "Bearer {token}"}
        assert not slack.users_can_save_always_allow
        assert app_custom.kind == "api"
        assert (app_custom.auth_mode, app_custom.auth_method) == ("none", None)
        assert _oauth_client(conn, app_custom.id) is None
        # A custom app with a header template: a saved user credential shows
        # that each user signs in. With none, the organization holds the key.
        app_integration = (
            "i.id = (SELECT integration_id FROM external_app WHERE id = :a)"
        )
        org_key = _copied(conn, app_integration, a=seeded.app_org_key)
        user_key = _copied(conn, app_integration, a=seeded.app_user_key)
        assert (org_key.auth_mode, org_key.auth_method) == ("shared", "api_key")
        assert (user_key.auth_mode, user_key.auth_method) == ("individual", "api_key")
        assert custom["private"].kind == "api"
        # App code reads a spec; the action sync writes its actions.
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
            "client_id": None,
            "client_secret": None,
            "registration": None,
        }
        assert (
            conn.execute(
                text("SELECT count(*) FROM integration_connection")
            ).scalar_one()
            == 0
        )

        # A private MCP server keeps its people. The default group becomes its
        # members.
        shared_users = set(
            conn.execute(
                text("SELECT user_id FROM plugin__user WHERE plugin_id = :p"),
                {"p": private.plugin_id},
            ).scalars()
        )
        assert shared_users == {seeded.other, seeded.admin}
        shared_groups = set(
            conn.execute(
                text(
                    "SELECT user_group_id FROM plugin__user_group WHERE plugin_id = :p"
                ),
                {"p": private.plugin_id},
            ).scalars()
        )
        assert shared_groups == {seeded.group}

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
            conn, "persona__plugin", "persona_id", seeded.own_persona, private.plugin_id
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
        # A skill that needs an app uses the integration of that app.
        assert conn.execute(
            text("SELECT integration_id FROM plugin__integration WHERE plugin_id = :p"),
            {"p": seeded.skill},
        ).scalars().all() == [slack.id]

        # Choices of users.
        preferences = {
            row.plugin_id: row.enabled
            for row in conn.execute(
                text(
                    "SELECT plugin_id, enabled FROM user_plugin_preference "
                    "WHERE user_id = :u"
                ),
                {"u": seeded.other},
            )
        }
        assert preferences == {
            public.plugin_id: False,
            custom["default"].plugin_id: False,
        }
        disabled = {
            row.assistant_id: row.disabled_plugin_ids
            for row in conn.execute(
                text(
                    "SELECT assistant_id, disabled_plugin_ids "
                    "FROM assistant__user_specific_config WHERE assistant_id = ANY(:p)"
                ),
                {"p": [seeded.persona, seeded.own_persona]},
            )
        }
        assert disabled == {seeded.persona: [public.plugin_id], seeded.own_persona: []}

        # Agents keep the same actions and no other.
        assert _settings(
            conn, "persona__plugin", "persona_id", seeded.persona, public.plugin_id
        ) == {"default": "blocked", "actions": {"list_issues": "inherit"}}
        assert _settings(
            conn, "persona__plugin", "persona_id", seeded.own_persona, public.plugin_id
        ) == {
            "default": "blocked",
            "actions": {"list_issues": "inherit", "create_issue": "inherit"},
        }
        assert (
            _settings(
                conn,
                "persona__plugin",
                "persona_id",
                seeded.persona,
                custom["shared"].plugin_id,
            )
            == {}
        )
        assert (
            _settings(
                conn,
                "persona__plugin",
                "persona_id",
                seeded.persona,
                private.plugin_id,
            )
            is None
        )
        # The bot freeze.
        assert _settings(
            conn, "persona__plugin", "persona_id", seeded.bot_persona, public.plugin_id
        ) == {"default": "blocked", "actions": {"create_issue": "allow"}}
        assert _settings(
            conn,
            "persona__plugin",
            "persona_id",
            seeded.bot_persona,
            custom["oauth"].plugin_id,
        ) == {"default": "allow"}
        assert (
            _settings(
                conn, "persona__plugin", "persona_id", 0, custom["default"].plugin_id
            )
            is not None
        )
        # The default agent leaves out a turned-off tool; a custom agent keeps it.
        assert custom["disabled"].installation_policy is None
        # Its only other agent is its owner's own, so it stays private.
        assert custom["disabled"].marketplace_kind == "user_uploads"
        assert (
            _settings(
                conn, "persona__plugin", "persona_id", 0, custom["disabled"].plugin_id
            )
            is None
        )
        assert (
            _settings(
                conn,
                "persona__plugin",
                "persona_id",
                seeded.own_persona,
                custom["disabled"].plugin_id,
            )
            == {}
        )

        # A task keeps its pre-approvals, and each other action asks.
        assert _settings(
            conn,
            "scheduled_task__plugin",
            "scheduled_task_id",
            seeded.task,
            slack.plugin_id,
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
        "persona__plugin",
        "scheduled_task__plugin",
        "plugin__integration",
        "plugin",
        "plugin_version",
        "plugin__user",
        "plugin__user_group",
        "user_plugin_preference",
        # With their integration_id.
        "mcp_server",
        "external_app",
        "tool",
    )
    first = _fingerprint(engine, new_tables)
    old = _fingerprint(engine, OLD_TABLES, ignore="integration_id")

    _migrate("downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT to_regclass('integration')")).scalar_one() is None
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM plugin WHERE id = :id"),
                {
                    "id": hashlib.md5(
                        f"integration_plugin:{seeded.gated['mcp_public']}".encode()
                    ).hexdigest()
                },
            ).scalar_one()
            == 0
        )
        for table in ("mcp_server", "external_app", "tool"):
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = 'integration_id'"
                    ),
                    {"t": table},
                ).scalar_one()
                == 0
            )
    assert _fingerprint(engine, OLD_TABLES, ignore="integration_id") == old

    _migrate("upgrade", REVISION)
    assert _fingerprint(engine, new_tables) == first


def test_share_publish_and_delete_a_home_plugin(engine: Engine, seeded: Seeded) -> None:
    _migrate("upgrade", "head")
    with engine.connect() as conn:
        integration_id = seeded.gated["mcp_private"]
        plugin_id = conn.execute(
            text("SELECT plugin_id FROM integration WHERE id = :id"),
            {"id": integration_id},
        ).scalar_one()

    with Session(engine) as db_session:
        apply_plugin_access_change__no_commit(
            [plugin_id],
            PluginAccessChange(
                user_grants=(
                    PluginUserGrant(seeded.other, SkillSharePermission.EDITOR),
                ),
                publish=True,
                on_name_clash="rename",
            ),
            None,
            db_session,
        ).raise_first_failure()
        db_session.commit()

    with engine.begin() as conn:
        plugin = conn.execute(
            text(
                "SELECT marketplace_id, published_version_id = current_version_id "
                "AS published FROM plugin WHERE id = :id"
            ),
            {"id": plugin_id},
        ).one()
        assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID and plugin.published
        assert (
            conn.execute(
                text(
                    "SELECT permission FROM plugin__user "
                    "WHERE plugin_id = :p AND user_id = :u"
                ),
                {"p": plugin_id, "u": seeded.other},
            ).scalar_one()
            == "EDITOR"
        )

        conn.execute(text("DELETE FROM plugin WHERE id = :id"), {"id": plugin_id})
        # The MCP server stays; old code still reads it.
        assert _kind_integration(conn, "mcp_server", seeded.mcp_private) is None
        for table in (
            "integration",
            "integration_action",
            "integration_action_policy",
        ):
            column = "id" if table == "integration" else "integration_id"
            assert (
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                    {"id": integration_id},
                ).scalar_one()
                == 0
            )


def test_user_delete_keeps_private_integrations_for_their_people(
    engine: Engine, seeded: Seeded
) -> None:
    """A user delete moves each private integration of the user to the
    Organization library as Not available, with its shares. It does not block
    the delete as a private skill does."""
    _migrate("upgrade", "head")
    with Session(engine) as db_session:
        owner = db_session.get(User, seeded.owner)
        assert owner is not None
        delete_user_from_db__no_commit(owner, db_session)
        db_session.commit()

    with engine.connect() as conn:
        for tool_id in (seeded.custom_private, seeded.custom_disabled):
            plugin = conn.execute(
                text(
                    "SELECT p.marketplace_id, p.installation_policy, "
                    "p.published_version_id = p.current_version_id AS published, "
                    "p.author_user_id FROM integration i "
                    f"JOIN plugin p ON p.id = i.plugin_id WHERE {TOOL_INTEGRATION}"
                ),
                {"t": tool_id},
            ).one()
            assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
            assert plugin.installation_policy == "NOT_AVAILABLE"
            assert plugin.published and plugin.author_user_id is None


def test_publishing_a_skill_named_like_an_integration(
    engine: Engine, seeded: Seeded
) -> None:
    """A home plugin holds no skill, so a skill with its name still publishes.
    Only the plugin label takes a free name."""
    _migrate("upgrade", "head")
    with engine.connect() as conn:
        integration_name = conn.execute(
            text(
                "SELECT p.name FROM integration i JOIN plugin p ON p.id = i.plugin_id "
                f"WHERE {TOOL_INTEGRATION}"
            ),
            {"t": seeded.custom_shared},
        ).scalar_one()
    skill_ids = [uuid4(), uuid4()]

    def publish(skill_id: UUID) -> None:
        with Session(engine) as db_session:
            skill = Skill(
                id=skill_id,
                name=integration_name,
                description="",
                bundle_file_id=f"u1-{skill_id.hex}",
                bundle_sha256="0" * 64,
                author_user_id=seeded.other,
            )
            db_session.add(skill)
            db_session.flush()
            create_skill_plugin__no_commit(
                skill, legacy_skill_version_content(skill), None, db_session
            )
            publish_plugin__no_commit(skill_id, "raise", db_session)
            db_session.commit()

    try:
        publish(skill_ids[0])
        with engine.connect() as conn:
            plugin = conn.execute(
                text("SELECT name, marketplace_id FROM plugin WHERE id = :id"),
                {"id": skill_ids[0]},
            ).one()
        assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert plugin.name == f"{integration_name}-2"
        # The first skill holds the name behind the "-2" label, so a second
        # skill with the name is refused.
        with pytest.raises(OnyxError) as refused:
            publish(skill_ids[1])
        assert refused.value.error_code == OnyxErrorCode.CONFLICT
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM plugin WHERE id = ANY(:ids)"), {"ids": skill_ids}
            )
            conn.execute(
                text("DELETE FROM skill WHERE id = ANY(:ids)"), {"ids": skill_ids}
            )
