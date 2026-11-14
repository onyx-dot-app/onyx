"""Add the integration tables and copy each MCP server, external app and
OpenAPI custom tool into them, with a home plugin for each.

The migration only adds. It reads the old tables and changes none of them, so
a rollback finds them as they were. It moves no secret: the credential import
(U3) does that in app code.

Revision ID: 730bce2814a0
Revises: 7c00f53ab75f
Create Date: 2026-11-13 14:42:45.411165

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "730bce2814a0"
down_revision = "7c00f53ab75f"
branch_labels = None
depends_on = None


ORGANIZATION_LIBRARY_ID = "00000000-0000-4000-8000-00000000011b"
# Records of a gated action. Each gets the integration of its gated_app_id.
RECORD_TABLES = ("action_receipt", "action_approval", "approval_request")
# Created-at of a row whose source has no timestamp (tool rows have none).
FALLBACK_CREATED_AT = "2026-11-13 00:00:00+00"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _create_tables() -> None:
    op.create_table(
        "integration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "config",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("actions", postgresql.JSONB(), nullable=True),
        sa.Column("actions_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_mode", sa.String(), nullable=False),
        sa.Column("auth_method", sa.String(), nullable=True),
        sa.Column("oauth_client_id", sa.LargeBinary(), nullable=True),
        sa.Column("oauth_client_secret", sa.LargeBinary(), nullable=True),
        sa.Column("oauth_settings", postgresql.JSONB(), nullable=True),
        sa.Column("credential_fields", postgresql.JSONB(), nullable=True),
        sa.Column("header_template", postgresql.JSONB(), nullable=True),
        sa.Column(
            "users_can_save_always_allow",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("legacy_tool_id", sa.Integer(), nullable=True, unique=True),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('mcp_server', 'app')", name="ck_integration_kind"),
        sa.CheckConstraint(
            "auth_mode IN ('none', 'shared', 'individual')",
            name="ck_integration_auth_mode",
        ),
        sa.CheckConstraint(
            "auth_method IN ('oauth2', 'api_key', 'onyx_login', 'managed')",
            name="ck_integration_auth_method",
        ),
    )

    op.create_table(
        "integration_connection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL: the shared connection of the organization.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("secret", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_scopes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("status", sa.String(), server_default="connected", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('connected', 'needs_reconnect')",
            name="ck_integration_connection_status",
        ),
    )
    op.create_index(
        "uq_integration_connection_organization",
        "integration_connection",
        ["integration_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_integration_connection_user",
        "integration_connection",
        ["user_id", "integration_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    op.create_table(
        "integration_action_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # '': the default for each action with no row of its own.
        sa.Column("action", sa.String(), server_default="", nullable=False),
        # NULL: the admin value. Set: the saved choice of one user.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("policy", sa.String(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "policy IN ('allow', 'auto', 'ask', 'blocked')",
            name="ck_integration_action_policy_policy",
        ),
    )
    op.create_index(
        "uq_integration_action_policy_admin",
        "integration_action_policy",
        ["integration_id", "action"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_integration_action_policy_user",
        "integration_action_policy",
        ["user_id", "integration_id", "action"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # action_settings: {"default": <value>, "actions": {<action>: <value>}},
    # each value inherit, allow, ask or blocked. A missing key is inherit.
    op.create_table(
        "persona__plugin",
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "action_settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_persona__plugin_plugin_id", "persona__plugin", ["plugin_id"])

    op.create_table(
        "scheduled_task__plugin",
        sa.Column(
            "scheduled_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_task.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "action_settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_scheduled_task__plugin_plugin_id",
        "scheduled_task__plugin",
        ["plugin_id"],
    )

    for table in RECORD_TABLES:
        op.add_column(table, sa.Column("integration_id", sa.Integer(), nullable=True))
        # NOT VALID: no scan of the old rows under a lock. The constraint still
        # checks each new or changed row, so the backfill below is checked too.
        op.create_foreign_key(
            f"fk_{table}_integration_id",
            table,
            "integration",
            ["integration_id"],
            ["id"],
            ondelete="SET NULL",
            postgresql_not_valid=True,
        )

    op.add_column(
        "assistant__user_specific_config",
        sa.Column(
            "disabled_plugin_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
    )


# One row for each integration of today, with its id and the plugin it gets.
# A gated_app row keeps its id. Each other MCP server, external app and
# OpenAPI custom tool takes the next id, in this order.
_CREATE_SOURCES = f"""
    CREATE TEMP TABLE integration_source ON COMMIT DROP AS
    WITH default_chat_tool AS (
        SELECT pt.tool_id
        FROM persona__tool pt
        JOIN persona p ON p.id = pt.persona_id
        WHERE p.id = 0 AND p.builtin_persona AND NOT p.deleted
    ),
    openapi_tool AS (
        SELECT t.*
        FROM tool t
        WHERE jsonb_typeof(t.openapi_schema) = 'object'
          AND t.in_code_tool_id IS NULL
          AND t.mcp_server_id IS NULL
    ),
    mcp AS (
        SELECT
            s.*,
            g.id AS gated_app_id,
            g.users_can_manage_policies,
            owner_user.id AS owner_user_id,
            EXISTS (
                SELECT 1 FROM mcp_server__user_group sg
                JOIN user_group ug ON ug.id = sg.user_group_id
                WHERE sg.mcp_server_id = s.id
                  AND ug.is_default AND ug.name = 'Basic'
            ) AS shared_with_basic,
            EXISTS (
                SELECT 1 FROM tool t
                WHERE t.mcp_server_id = s.id
                  AND t.id IN (SELECT tool_id FROM default_chat_tool)
            ) AS is_default_chat
        FROM mcp_server s
        LEFT JOIN gated_app g ON g.mcp_server_id = s.id
        LEFT JOIN "user" owner_user ON owner_user.email = s.owner
    ),
    candidates AS (
        SELECT
            g.id AS gated_app_id,
            CASE WHEN g.id IS NULL THEN 1 END AS ungated_rank,
            'app' AS kind,
            a.id AS external_app_id,
            NULL::integer AS mcp_server_id,
            NULL::integer AS tool_id,
            a.name,
            NULL::text AS description,
            a.enabled,
            jsonb_build_object(
                'preset',
                CASE WHEN a.app_type <> 'CUSTOM' THEN lower(a.app_type) END,
                'url_patterns', to_jsonb(a.upstream_url_patterns)
            ) AS config,
            NULL::jsonb AS actions,
            NULL::timestamptz AS actions_synced_at,
            CASE
                WHEN a.app_type <> 'CUSTOM' THEN 'individual'
                WHEN a.auth_template = '{{}}'::jsonb THEN 'none'
                ELSE 'shared'
            END AS auth_mode,
            CASE
                WHEN a.app_type <> 'CUSTOM' THEN 'oauth2'
                WHEN a.auth_template <> '{{}}'::jsonb THEN 'api_key'
            END AS auth_method,
            NULL::jsonb AS oauth_settings,
            NULLIF(a.auth_template, '{{}}'::jsonb) AS header_template,
            coalesce(g.users_can_manage_policies, true)
                AS users_can_save_always_allow,
            NULL::integer AS legacy_tool_id,
            'organization_library' AS placement,
            NULL::uuid AS author_user_id,
            -- An admin turns each app on again.
            'NOT_AVAILABLE' AS installation_policy,
            a.created_at,
            a.updated_at
        FROM external_app a
        LEFT JOIN gated_app g ON g.external_app_id = a.id

        UNION ALL

        SELECT
            m.gated_app_id,
            CASE WHEN m.gated_app_id IS NULL THEN 0 END,
            'mcp_server',
            NULL,
            m.id,
            NULL,
            m.name,
            m.description,
            true,
            jsonb_strip_nulls(jsonb_build_object(
                'server_url', m.server_url, 'transport', m.transport
            )),
            coalesce(
                (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'name', t.name,
                            'description', t.description,
                            'input_schema', t.mcp_input_schema,
                            'output_schema', t.mcp_output_schema,
                            'read_only', t.mcp_read_only
                        )
                        ORDER BY t.name, t.id
                    )
                    FROM tool t
                    WHERE t.mcp_server_id = m.id
                ),
                '[]'::jsonb
            ),
            m.last_refreshed_at,
            CASE
                WHEN coalesce(m.auth_type, 'NONE') = 'NONE' THEN 'none'
                WHEN m.auth_type = 'PT_OAUTH' THEN 'individual'
                WHEN m.auth_performer = 'PER_USER' THEN 'individual'
                ELSE 'shared'
            END,
            CASE m.auth_type
                WHEN 'API_TOKEN' THEN 'api_key'
                WHEN 'OAUTH' THEN 'oauth2'
                WHEN 'PT_OAUTH' THEN 'onyx_login'
            END,
            CASE WHEN m.auth_type = 'OAUTH' THEN jsonb_strip_nulls(
                jsonb_build_object(
                    'provider_mode', m.oauth_provider_mode,
                    'authorization_url', m.oauth_authorization_endpoint,
                    'token_url', m.oauth_token_endpoint,
                    'scopes', m.oauth_scopes_override,
                    'additional_params', m.oauth_additional_auth_params,
                    'cimd_enabled', m.oauth_cimd_enabled
                )
            ) END,
            NULL::jsonb,
            coalesce(m.users_can_manage_policies, true),
            NULL,
            CASE
                WHEN m.is_public OR m.shared_with_basic
                    OR m.owner_user_id IS NULL
                    THEN 'organization_library'
                ELSE 'user_uploads'
            END,
            CASE
                WHEN NOT (m.is_public OR m.shared_with_basic)
                    THEN m.owner_user_id
            END,
            CASE
                WHEN NOT (m.is_public OR m.shared_with_basic)
                    AND m.owner_user_id IS NULL
                    THEN 'NOT_AVAILABLE'
                WHEN m.is_default_chat THEN 'DEFAULT'
            END,
            coalesce(m.created_at, TIMESTAMPTZ '{FALLBACK_CREATED_AT}'),
            coalesce(
                m.updated_at, m.created_at, TIMESTAMPTZ '{FALLBACK_CREATED_AT}'
            )
        FROM mcp m

        UNION ALL

        SELECT
            NULL,
            2,
            'app',
            NULL,
            NULL,
            t.id,
            coalesce(nullif(t.display_name, ''), t.name),
            t.description,
            true,
            jsonb_build_object('openapi_schema', t.openapi_schema),
            NULL,
            NULL,
            CASE
                WHEN t.oauth_config_id IS NOT NULL OR t.passthrough_auth
                    THEN 'individual'
                WHEN jsonb_typeof(t.custom_headers) = 'array'
                    AND jsonb_array_length(t.custom_headers) > 0
                    THEN 'shared'
                ELSE 'none'
            END,
            CASE
                WHEN t.oauth_config_id IS NOT NULL THEN 'oauth2'
                WHEN t.passthrough_auth THEN 'onyx_login'
                WHEN jsonb_typeof(t.custom_headers) = 'array'
                    AND jsonb_array_length(t.custom_headers) > 0
                    THEN 'api_key'
            END,
            (
                SELECT jsonb_strip_nulls(jsonb_build_object(
                    'authorization_url', o.authorization_url,
                    'token_url', o.token_url,
                    'scopes', o.scopes,
                    'additional_params', o.additional_params,
                    'pkce', o.supports_pkce
                ))
                FROM oauth_config o
                WHERE o.id = t.oauth_config_id
            ),
            NULL,
            true,
            t.id,
            CASE
                WHEN t.user_id IS NULL OR is_shared.value
                    THEN 'organization_library'
                ELSE 'user_uploads'
            END,
            t.user_id,
            CASE WHEN is_default.value THEN 'DEFAULT' END,
            TIMESTAMPTZ '{FALLBACK_CREATED_AT}',
            TIMESTAMPTZ '{FALLBACK_CREATED_AT}'
        FROM openapi_tool t
        CROSS JOIN LATERAL (
            SELECT t.enabled AND t.id IN (SELECT tool_id FROM default_chat_tool)
                AS value
        ) is_default
        -- Shared: a default chat tool, or on an agent that other people use.
        CROSS JOIN LATERAL (
            SELECT is_default.value OR EXISTS (
                SELECT 1
                FROM persona__tool pt
                JOIN persona p ON p.id = pt.persona_id
                WHERE pt.tool_id = t.id
                  AND NOT p.deleted
                  -- The default agent leaves out a tool the admin turned off.
                  AND NOT (p.id = 0 AND NOT t.enabled)
                  AND (
                      p.user_id IS DISTINCT FROM t.user_id
                      OR p.is_public
                      OR p.owner_group_id IS NOT NULL
                      OR EXISTS (
                          SELECT 1 FROM persona__user pu
                          WHERE pu.persona_id = p.id
                            AND pu.user_id IS DISTINCT FROM t.user_id
                      )
                      OR EXISTS (
                          SELECT 1 FROM persona__user_group pg
                          WHERE pg.persona_id = p.id
                      )
                  )
            ) AS value
        ) is_shared
    )
    SELECT
        md5('integration_plugin:' || numbered.id::text)::uuid AS plugin_id,
        CASE placement
            WHEN 'organization_library' THEN '{ORGANIZATION_LIBRARY_ID}'::uuid
            ELSE md5('user_uploads:' || author_user_id::text)::uuid
        END AS marketplace_id,
        numbered.*
    FROM (
        SELECT
            coalesce(
                gated_app_id,
                coalesce((SELECT max(id) FROM gated_app), 0)
                    + row_number() OVER (
                        PARTITION BY gated_app_id IS NULL
                        ORDER BY ungated_rank,
                            coalesce(mcp_server_id, external_app_id, tool_id)
                    )
            ) AS id,
            candidates.*
        FROM candidates
    ) numbered
"""

_INSERT_ORGANIZATION_LIBRARY = f"""
    INSERT INTO plugin_marketplace
        (id, kind, name, owner_user_id, default_installation_policy, created_at)
    VALUES (
        '{ORGANIZATION_LIBRARY_ID}',
        'organization_library',
        'Organization library',
        NULL,
        'AVAILABLE',
        TIMESTAMPTZ '2026-11-11 00:00:00+00'
    )
    ON CONFLICT DO NOTHING
"""

_INSERT_USER_UPLOADS = """
    INSERT INTO plugin_marketplace
        (id, kind, name, owner_user_id, default_installation_policy, created_at)
    SELECT
        marketplace_id, 'user_uploads', 'My uploads', author_user_id,
        'AVAILABLE', min(created_at)
    FROM integration_source
    WHERE placement = 'user_uploads'
    GROUP BY marketplace_id, author_user_id
    ON CONFLICT DO NOTHING
"""

# The free-name rule of the plugin backfill (cdec9dd9ca3d): a used name takes
# the first free <name>-2, <name>-3, ... in its marketplace, cut to fit in 64
# characters. integration.name keeps the full name.
_INSERT_PLUGINS = """
    DO $$
    DECLARE
        pending record;
        base text;
        candidate text;
        suffix integer;
    BEGIN
        FOR pending IN
            SELECT * FROM integration_source ORDER BY created_at, id
        LOOP
            base := left(pending.name, 64);
            candidate := base;
            suffix := 1;
            WHILE EXISTS (
                SELECT 1 FROM plugin
                WHERE marketplace_id = pending.marketplace_id
                  AND name = candidate
            ) LOOP
                suffix := suffix + 1;
                candidate := left(base, 63 - length(suffix::text))
                    || '-' || suffix::text;
            END LOOP;
            INSERT INTO plugin (
                id, name, description, marketplace_id, author_user_id,
                installation_policy, current_version_id, published_version_id,
                created_at, updated_at
            )
            VALUES (
                pending.plugin_id, candidate,
                coalesce(pending.description, ''),
                pending.marketplace_id, pending.author_user_id,
                pending.installation_policy, pending.plugin_id,
                CASE WHEN pending.placement = 'organization_library'
                    THEN pending.plugin_id END,
                pending.created_at, pending.updated_at
            );
        END LOOP;
    END
    $$
"""

# Version 1 has no bundle and no skill. Its id is the plugin id.
_INSERT_VERSIONS = """
    INSERT INTO plugin_version (
        id, plugin_id, version_number, created_by_user_id, created_by_email,
        created_at
    )
    SELECT src.plugin_id, src.plugin_id, 1, src.author_user_id, u.email,
        src.created_at
    FROM integration_source src
    LEFT JOIN "user" u ON u.id = src.author_user_id
"""

_INSERT_INTEGRATIONS = """
    INSERT INTO integration (
        id, kind, name, description, plugin_id, enabled, config, actions,
        actions_synced_at, auth_mode, auth_method, oauth_settings,
        header_template, users_can_save_always_allow, legacy_tool_id,
        created_at, updated_at
    )
    SELECT
        id, kind, name, description, plugin_id, enabled, config, actions,
        actions_synced_at, auth_mode, auth_method, oauth_settings,
        header_template, users_can_save_always_allow, legacy_tool_id,
        created_at, updated_at
    FROM integration_source
"""

_SET_INTEGRATION_SEQUENCE = """
    SELECT setval(
        pg_get_serial_sequence('integration', 'id'),
        coalesce((SELECT max(id) FROM integration), 1),
        (SELECT max(id) FROM integration) IS NOT NULL
    )
"""

# Each tool of an integration: the OpenAPI tool itself, or each tool row of an
# MCP server.
_CREATE_TOOL_INTEGRATIONS = """
    CREATE TEMP TABLE tool_integration ON COMMIT DROP AS
    SELECT t.id AS tool_id, t.name AS tool_name, src.id AS integration_id,
        src.plugin_id, src.kind
    FROM integration_source src
    JOIN tool t
      ON t.id = src.legacy_tool_id OR t.mcp_server_id = src.mcp_server_id
"""

# A private MCP server keeps its people. Basic makes the server public (it is
# in the Organization library), and phase 3 counts no default group, so a
# share with Admin becomes a share with each member of Admin.
_INSERT_MCP_USER_SHARES = """
    INSERT INTO plugin__user (plugin_id, user_id, permission, created_at)
    SELECT src.plugin_id, su.user_id, 'VIEWER', src.created_at
    FROM integration_source src
    JOIN mcp_server__user su ON su.mcp_server_id = src.mcp_server_id
    WHERE src.placement = 'user_uploads'
       OR src.installation_policy = 'NOT_AVAILABLE'
    UNION
    SELECT src.plugin_id, uug.user_id, 'VIEWER', src.created_at
    FROM integration_source src
    JOIN mcp_server__user_group sg ON sg.mcp_server_id = src.mcp_server_id
    JOIN user_group ug ON ug.id = sg.user_group_id AND ug.is_default
    JOIN user__user_group uug ON uug.user_group_id = ug.id
    WHERE (src.placement = 'user_uploads'
           OR src.installation_policy = 'NOT_AVAILABLE')
      AND uug.user_id IS NOT NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_MCP_GROUP_SHARES = """
    INSERT INTO plugin__user_group
        (plugin_id, user_group_id, permission, installation_policy, created_at)
    SELECT src.plugin_id, sg.user_group_id, 'VIEWER', NULL, src.created_at
    FROM integration_source src
    JOIN mcp_server__user_group sg ON sg.mcp_server_id = src.mcp_server_id
    JOIN user_group ug ON ug.id = sg.user_group_id AND NOT ug.is_default
    WHERE src.placement = 'user_uploads'
       OR src.installation_policy = 'NOT_AVAILABLE'
"""

_POLICY_VALUE = """
    CASE {column}
        WHEN 'ALWAYS' THEN 'allow'
        WHEN 'ASK' THEN 'ask'
        WHEN 'DENY' THEN 'blocked'
    END
"""

# An MCP tool that the admin did not select is offered nowhere today. Blocked
# keeps it so; this row wins over a policy row for the same tool.
_INSERT_UNSELECTED_MCP_TOOLS = """
    INSERT INTO integration_action_policy
        (integration_id, action, user_id, policy, created_at, updated_at)
    SELECT ti.integration_id, ti.tool_name, NULL, 'blocked',
        src.created_at, src.updated_at
    FROM tool_integration ti
    JOIN integration_source src ON src.id = ti.integration_id
    JOIN tool t ON t.id = ti.tool_id
    WHERE ti.kind = 'mcp_server' AND NOT t.enabled
    ORDER BY ti.integration_id, ti.tool_name
    ON CONFLICT DO NOTHING
"""

_INSERT_ADMIN_POLICIES = f"""
    INSERT INTO integration_action_policy
        (integration_id, action, user_id, policy, created_at, updated_at)
    SELECT w.gated_app_id, w.action_id, NULL,
        {_POLICY_VALUE.format(column="w.policy")},
        w.created_at, w.updated_at
    FROM workspace_action_policy w
    ORDER BY w.gated_app_id, w.action_id
    ON CONFLICT DO NOTHING
"""

_INSERT_USER_POLICIES = f"""
    INSERT INTO integration_action_policy
        (integration_id, action, user_id, policy, created_at, updated_at)
    SELECT u.gated_app_id, u.action_id, u.user_id,
        {_POLICY_VALUE.format(column="u.policy")},
        TIMESTAMPTZ '{FALLBACK_CREATED_AT}', TIMESTAMPTZ '{FALLBACK_CREATED_AT}'
    FROM user_action_policy u
    ORDER BY u.user_id, u.gated_app_id, u.action_id
"""

# The chat value wins; enabled_in_craft is not copied.
_INSERT_PREFERENCES = """
    INSERT INTO user_plugin_preference (user_id, plugin_id, enabled, enabled_at)
    SELECT p.user_id, src.plugin_id, p.enabled_in_chat, NULL::timestamptz
    FROM mcp_server_user_preference p
    JOIN integration_source src ON src.mcp_server_id = p.mcp_server_id
    UNION ALL
    SELECT p.user_id, src.plugin_id, p.enabled_in_chat, NULL::timestamptz
    FROM tool_user_preference p
    JOIN integration_source src ON src.legacy_tool_id = p.tool_id
"""

# A plugin is off for the user on that agent when the user turned off each
# tool that the agent has of it. disabled_tool_ids does not change.
_SET_DISABLED_PLUGINS = """
    UPDATE assistant__user_specific_config c
    SET disabled_plugin_ids = off.plugin_ids
    FROM (
        SELECT assistant_id, user_id, array_agg(plugin_id ORDER BY plugin_id)
            AS plugin_ids
        FROM (
            SELECT cfg.assistant_id, cfg.user_id, ti.plugin_id
            FROM assistant__user_specific_config cfg
            JOIN persona__tool pt ON pt.persona_id = cfg.assistant_id
            JOIN tool_integration ti ON ti.tool_id = pt.tool_id
            GROUP BY cfg.assistant_id, cfg.user_id, ti.plugin_id
            HAVING bool_and(pt.tool_id = ANY(cfg.disabled_tool_ids))
        ) per_plugin
        GROUP BY assistant_id, user_id
    ) off
    WHERE c.assistant_id = off.assistant_id AND c.user_id = off.user_id
"""

# The bot freeze: an agent that a Slack or Discord bot runs keeps each action
# it has with Allow. A bot with no agent set runs the default agent (id 0).
_BOT_PERSONAS = """
    SELECT persona_id FROM slack_channel_config WHERE persona_id IS NOT NULL
    UNION
    SELECT 0 FROM slack_channel_config WHERE persona_id IS NULL
    UNION
    SELECT default_persona_id FROM discord_guild_config
    WHERE default_persona_id IS NOT NULL
    UNION
    SELECT 0 FROM discord_guild_config WHERE default_persona_id IS NULL
    UNION
    SELECT persona_override_id FROM discord_channel_config
    WHERE persona_override_id IS NOT NULL
"""

# An agent keeps the MCP tools it has (inherit, or allow for a bot agent).
# Each other tool, now or added later, is blocked by the default. An agent
# with a custom tool gets empty settings, or allow for a bot agent.
_INSERT_PERSONA_PLUGINS = f"""
    INSERT INTO persona__plugin (persona_id, plugin_id, action_settings)
    SELECT
        pt.persona_id,
        ti.plugin_id,
        CASE
            WHEN ti.kind = 'mcp_server' THEN jsonb_build_object(
                'default', 'blocked',
                'actions', jsonb_object_agg(
                    ti.tool_name,
                    CASE WHEN bot.persona_id IS NOT NULL
                        THEN 'allow' ELSE 'inherit' END
                )
            )
            WHEN bot.persona_id IS NOT NULL
                THEN '{{"default": "allow"}}'::jsonb
            ELSE '{{}}'::jsonb
        END
    FROM persona__tool pt
    JOIN tool_integration ti ON ti.tool_id = pt.tool_id
    JOIN tool t ON t.id = ti.tool_id
    LEFT JOIN ({_BOT_PERSONAS}) bot ON bot.persona_id = pt.persona_id
    -- The default agent leaves out an OpenAPI tool that the admin turned off.
    WHERE NOT (pt.persona_id = 0 AND ti.kind = 'app' AND NOT t.enabled)
    GROUP BY pt.persona_id, ti.plugin_id, ti.kind, bot.persona_id
"""

# A task keeps its pre-approvals. Each other action asks, as it does today
# for a task with no saved choice.
_INSERT_TASK_PLUGINS = f"""
    INSERT INTO scheduled_task__plugin
        (scheduled_task_id, plugin_id, action_settings)
    SELECT
        e.scheduled_task_id,
        src.plugin_id,
        jsonb_build_object(
            'default', 'ask',
            'actions', coalesce(
                (
                    SELECT jsonb_object_agg(
                        p.action_id, {_POLICY_VALUE.format(column="p.policy")}
                    )
                    FROM scheduled_task_action_policy p
                    WHERE p.scheduled_task_id = e.scheduled_task_id
                      AND p.gated_app_id = e.gated_app_id
                ),
                '{{}}'::jsonb
            )
        )
    FROM scheduled_task_enabled_app e
    JOIN integration_source src ON src.gated_app_id = e.gated_app_id
"""

_SET_RECORD_INTEGRATIONS = [
    f"UPDATE {table} SET integration_id = gated_app_id WHERE gated_app_id IS NOT NULL"
    for table in RECORD_TABLES
]


def _copy_integrations() -> None:
    for statement in (
        _CREATE_SOURCES,
        _INSERT_ORGANIZATION_LIBRARY,
        _INSERT_USER_UPLOADS,
        _INSERT_PLUGINS,
        _INSERT_VERSIONS,
        _INSERT_INTEGRATIONS,
        _SET_INTEGRATION_SEQUENCE,
        _CREATE_TOOL_INTEGRATIONS,
        _INSERT_MCP_USER_SHARES,
        _INSERT_MCP_GROUP_SHARES,
        _INSERT_UNSELECTED_MCP_TOOLS,
        _INSERT_ADMIN_POLICIES,
        _INSERT_USER_POLICIES,
        _INSERT_PREFERENCES,
        _SET_DISABLED_PLUGINS,
        _INSERT_PERSONA_PLUGINS,
        _INSERT_TASK_PLUGINS,
        *_SET_RECORD_INTEGRATIONS,
        "DROP TABLE tool_integration",
        "DROP TABLE integration_source",
    ):
        op.execute(statement)


def upgrade() -> None:
    _create_tables()
    _copy_integrations()


def downgrade() -> None:
    op.drop_column("assistant__user_specific_config", "disabled_plugin_ids")
    for table in reversed(RECORD_TABLES):
        op.drop_column(table, "integration_id")
    for table in (
        "scheduled_task__plugin",
        "persona__plugin",
        "integration_action_policy",
        "integration_connection",
    ):
        op.drop_table(table)
    # Each home plugin goes with its integration.
    op.execute("DELETE FROM plugin WHERE id IN (SELECT plugin_id FROM integration)")
    op.drop_table("integration")
