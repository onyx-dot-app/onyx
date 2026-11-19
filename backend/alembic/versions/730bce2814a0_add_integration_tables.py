"""Add the integration tables and copy each MCP server, external app and
OpenAPI custom tool into them. Each integration stands alone and owns its
access: its owner, its install setting, its shares and the on/off choice of
each user. An agent and a task link to an integration directly. The copy
makes no plugin.

The old tables stay the tables of each kind: each integration points at its
mcp_server, external_app or OpenAPI tool row, as gated_app does. The old tables
only get new columns, and approval_request.gated_app_id becomes nullable; a
rollback undoes both. The data copy is SQL only. It moves no secret in
clear: each credential is copied as its encrypted bytes.

The copy decrypts one value: the admin config of a per-user API key MCP
server, to read its header template, which holds no secret. The actions of an
OpenAPI spec or a built-in app catalog are not copied. The app writes them on
first read (onyx/integrations/actions.py).

Revision ID: 730bce2814a0
Revises: 2bb0e564ae2d
Create Date: 2026-11-13 14:42:45.411165

"""

import base64
import json
import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import op
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "730bce2814a0"
down_revision = "2bb0e564ae2d"
branch_labels = None
depends_on = None


# Records of a gated action. Each gets the integration of its gated_app_id.
RECORD_TABLES = ("action_receipt", "action_approval", "approval_request")
# Alembic runs all pending revisions of a schema in one transaction, so while
# this retries, the locks of earlier revisions stay held. Keep the budget short.
_LOCK_TIMEOUT = "5s"
_LOCK_ATTEMPTS = 6
_RETRY_DELAY_S = 2
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"
# The wait for the lock of each VALIDATE CONSTRAINT.
LOCK_TIMEOUT = "60s"
# Created-at of a row whose source has no timestamp (tool rows have none).
FALLBACK_CREATED_AT = "2026-11-13 00:00:00+00"
_INSTALLATION_POLICIES = ("REQUIRED", "DEFAULT", "AVAILABLE", "NOT_AVAILABLE")
# A frozen copy of the ciphertext formats of onyx/utils/encryption.py and
# ee/onyx/utils/encryption.py. Data at this revision was written in these
# formats, so the copy must not follow later changes to that code.
_ENVELOPE_MAGIC = b"\xffONYX"
_ENVELOPE_VERSION = 1
_LEGACY_KEY_ID = "legacy"
_LEGACY_ENVELOPE_KEY_INFO = b"onyx-envelope-v1-legacy"
_NONCE_BYTES = 12
_CBC_IV_BYTES = 16
_LEGACY_KEY_SIZES = (32, 24, 16)
_DENYLISTED_HEADERS = frozenset({"host"})
_TEMPLATE_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]+)\}")
_SHARE_PERMISSIONS = ("EDITOR", "VIEWER")


def _installation_policy_type() -> sa.Enum:
    return sa.Enum(*_INSTALLATION_POLICIES, native_enum=False)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _action_settings() -> sa.Column:
    return sa.Column(
        "action_settings",
        postgresql.JSONB(),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


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


def _is_lock_timeout(error: DBAPIError) -> bool:
    # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on the
    # driver error, but the DBAPI error type does not declare it.
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _with_bounded_lock_wait(change: Callable[[], None]) -> None:
    """Runs a change with a bounded lock wait, as 7c00f53ab75f does.

    An ALTER TABLE on a table that chat reads or writes waits for the open
    transactions on it, and chat queries queue behind that wait. A short
    lock_timeout keeps each wait short; each attempt runs in a savepoint, so a
    timeout retries instead of failing the migration.
    """
    bind = op.get_bind()
    for attempt in range(1, _LOCK_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                change()
            break
        except DBAPIError as e:
            if attempt == _LOCK_ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "An integration tables change timed out waiting for a lock "
                "(attempt %s/%s). Retrying in %ss.",
                attempt,
                _LOCK_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)


def _alter_old_tables() -> None:
    """Add the new columns to the old tables that chat and tools use."""
    op.add_column(
        "assistant__user_specific_config",
        sa.Column(
            "disabled_integration_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default="{}",
            nullable=False,
        ),
    )

    # No default: the column is added with no rewrite of chat_session.
    op.add_column(
        "chat_session", sa.Column("tool_options", postgresql.JSONB(), nullable=True)
    )

    # An approval for an integration made after the upgrade has no gated_app.
    op.alter_column(
        "approval_request", "gated_app_id", existing_type=sa.Integer(), nullable=True
    )

    for table in RECORD_TABLES:
        op.add_column(table, sa.Column("integration_id", sa.Integer(), nullable=True))
        # NOT VALID: no scan of the old rows under the ALTER TABLE lock. The
        # constraint still checks each new or changed row, so the backfill of
        # the copy is checked too. upgrade() validates it after the commit.
        op.create_foreign_key(
            f"fk_{table}_integration_id",
            table,
            "integration",
            ["integration_id"],
            ["id"],
            ondelete="SET NULL",
            postgresql_not_valid=True,
        )


def _create_tables() -> None:
    op.create_table(
        "integration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # The owner always has access. NULL when not known or deleted. The
        # person who signs in is on integration_connection.
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The company install setting. NOT_AVAILABLE is private: only the
        # owner and the shares have access.
        sa.Column(
            "installation_policy",
            _installation_policy_type(),
            server_default="NOT_AVAILABLE",
            nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("auth_mode", sa.String(), nullable=False),
        sa.Column("auth_method", sa.String(), nullable=True),
        sa.Column("credential_fields", postgresql.JSONB(), nullable=True),
        sa.Column("header_template", postgresql.JSONB(), nullable=True),
        sa.Column(
            "users_can_save_always_allow",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        # NULL until the app fills the data that only app code can read.
        # The row of its kind that holds the settings: exactly one is set, and
        # it matches kind. Deleting that row deletes the integration.
        sa.Column(
            "mcp_server_id",
            sa.Integer(),
            sa.ForeignKey("mcp_server.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "external_app_id",
            sa.Integer(),
            sa.ForeignKey("external_app.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("tool.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        *_timestamps(),
        # Old code still writes the kind tables, so the database keeps each
        # integration tied to exactly one row of its kind.
        sa.CheckConstraint(
            "num_nonnulls(mcp_server_id, external_app_id, tool_id) = 1",
            name="ck_integration_single_kind_row",
        ),
        sa.CheckConstraint(
            "(kind = 'mcp') = (mcp_server_id IS NOT NULL)",
            name="ck_integration_kind_row",
        ),
        # The value checks of these tables: SQL migrations write the columns
        # as plain strings, past the enum type of the model. A value outside
        # the enum makes each ORM read of the row raise.
        sa.CheckConstraint("kind IN ('mcp', 'api')", name="ck_integration_kind"),
        sa.CheckConstraint(
            "auth_mode IN ('none', 'shared', 'individual')",
            name="ck_integration_auth_mode",
        ),
        sa.CheckConstraint(
            "auth_method IN ('oauth2', 'api_key', 'onyx_login', 'managed')",
            name="ck_integration_auth_method",
        ),
    )
    op.create_index("ix_integration_owner_user_id", "integration", ["owner_user_id"])

    op.create_table(
        "integration_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=True),
        sa.Column("default_policy", sa.String(), nullable=True),
        sa.Column("input_schema", postgresql.JSONB(), nullable=True),
        sa.Column("output_schema", postgresql.JSONB(), nullable=True),
        sa.Column("http_method", sa.String(), nullable=True),
        sa.Column("path_template", sa.String(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "integration_id", "key", name="uq_integration_action_integration_key"
        ),
        # A SQL migration can write a value outside the enum (see integration).
        sa.CheckConstraint(
            "source IN ('mcp', 'openapi', 'external_app')",
            name="ck_integration_action_source",
        ),
        sa.CheckConstraint(
            "default_policy IN ('allow', 'auto', 'ask', 'blocked')",
            name="ck_integration_action_default_policy",
        ),
    )

    op.create_table(
        "integration_oauth_client",
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider_mode", sa.String(), nullable=False),
        sa.Column("authorization_url", sa.Text(), nullable=True),
        sa.Column("token_url", sa.Text(), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("additional_params", postgresql.JSONB(), nullable=True),
        sa.Column("pkce", sa.Boolean(), nullable=True),
        sa.Column(
            "cimd_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("client_id", sa.LargeBinary(), nullable=True),
        sa.Column("client_secret", sa.LargeBinary(), nullable=True),
        sa.Column("registration", sa.LargeBinary(), nullable=True),
        # The old format of a secret that the migration copied as it was, such
        # as mcp_config. The credential code reads it, and writes the new
        # format on its next write. NULL: the new format.
        sa.Column("legacy_format", sa.String(), nullable=True),
        *_timestamps(),
        # A SQL migration can write a value outside the enum (see integration).
        sa.CheckConstraint(
            "provider_mode IN ('preset', 'manual', 'discovery')",
            name="ck_integration_oauth_client_provider_mode",
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
        # The old format of a secret that the migration copied as it was, such
        # as mcp_config. The credential code reads it, and writes the new
        # format on its next write. NULL: the new format.
        sa.Column("legacy_format", sa.String(), nullable=True),
        *_timestamps(),
        # A SQL migration can write a value outside the enum (see integration).
        sa.CheckConstraint(
            "status IN ('connected', 'needs_reconnect')",
            name="ck_integration_connection_status",
        ),
    )
    op.create_index(
        "ix_integration_connection_integration_id",
        "integration_connection",
        ["integration_id"],
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
        # Set: the saved choice of one user.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Set: the value for one group. Both NULL: the admin value.
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("policy", sa.String(), nullable=False),
        *_timestamps(),
        # A SQL migration can write a value outside the enum (see integration).
        sa.CheckConstraint(
            "policy IN ('allow', 'auto', 'ask', 'blocked')",
            name="ck_integration_action_policy_policy",
        ),
        # Each unique index covers one scope. A row with a user and a group
        # would be in two, and a writer of one scope cannot see the other.
        sa.CheckConstraint(
            "num_nonnulls(user_id, user_group_id) <= 1",
            name="ck_integration_action_policy_single_scope",
        ),
    )
    op.create_index(
        "ix_integration_action_policy_integration_id",
        "integration_action_policy",
        ["integration_id"],
    )
    op.create_index(
        "uq_integration_action_policy_admin",
        "integration_action_policy",
        ["integration_id", "action"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL AND user_group_id IS NULL"),
    )
    op.create_index(
        "uq_integration_action_policy_user",
        "integration_action_policy",
        ["user_id", "integration_id", "action"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    # The group leads, as the user does above, so a group delete finds its rows.
    op.create_index(
        "uq_integration_action_policy_user_group",
        "integration_action_policy",
        ["user_group_id", "integration_id", "action"],
        unique=True,
        postgresql_where=sa.text("user_group_id IS NOT NULL"),
    )

    # The access tables of an integration have the shape of the plugin ones.
    op.create_table(
        "integration__user",
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission",
            sa.Enum(*_SHARE_PERMISSIONS, native_enum=False),
            server_default="VIEWER",
            nullable=False,
        ),
        _created_at(),
    )
    op.create_index("ix_integration__user_user_id", "integration__user", ["user_id"])

    op.create_table(
        "integration__user_group",
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # NULL: the row holds only a group install setting and grants nothing.
        sa.Column(
            "permission",
            sa.Enum(*_SHARE_PERMISSIONS, native_enum=False),
            nullable=True,
        ),
        sa.Column("installation_policy", _installation_policy_type(), nullable=True),
        _created_at(),
    )
    op.create_index(
        "ix_integration__user_group_user_group_id",
        "integration__user_group",
        ["user_group_id"],
    )

    op.create_table(
        "user_integration_preference",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_integration_preference_integration_id",
        "user_integration_preference",
        ["integration_id"],
    )

    # The links of an agent and of a task to an integration. action_settings:
    # {"default": <value>, "actions": {<action>: <value>}}, each value
    # inherit, allow, ask or blocked. A missing key is inherit.
    op.create_table(
        "persona__integration",
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _action_settings(),
    )
    op.create_index(
        "ix_persona__integration_integration_id",
        "persona__integration",
        ["integration_id"],
    )

    op.create_table(
        "scheduled_task__integration",
        sa.Column(
            "scheduled_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_task.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _action_settings(),
    )
    op.create_index(
        "ix_scheduled_task__integration_integration_id",
        "scheduled_task__integration",
        ["integration_id"],
    )


# One row for each integration of today, with its id.
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
            'api' AS kind,
            a.id AS external_app_id,
            NULL::integer AS mcp_server_id,
            NULL::integer AS tool_id,
            a.name,
            NULL::text AS description,
            a.enabled,
            CASE
                WHEN a.app_type <> 'CUSTOM' THEN 'individual'
                WHEN a.auth_template = '{{}}'::jsonb THEN 'none'
                -- The organization credentials are encrypted, so SQL cannot
                -- see which fields a user must fill. A saved user credential
                -- shows that users fill some. This mode is final: the
                -- credential code reads the copied organization values as
                -- the defaults that a user's values override.
                WHEN EXISTS (
                    SELECT 1 FROM external_app_user_credential c
                    WHERE c.external_app_id = a.id
                ) THEN 'individual'
                ELSE 'shared'
            END AS auth_mode,
            CASE
                WHEN a.app_type <> 'CUSTOM' THEN 'oauth2'
                WHEN a.auth_template <> '{{}}'::jsonb THEN 'api_key'
            END AS auth_method,
            -- Provider code owns the endpoints of a built-in app.
            CASE WHEN a.app_type <> 'CUSTOM' THEN 'preset' END
                AS oauth_provider_mode,
            NULL::text AS oauth_authorization_url,
            NULL::text AS oauth_token_url,
            NULL::varchar[] AS oauth_scopes,
            NULL::jsonb AS oauth_additional_params,
            NULL::boolean AS oauth_pkce,
            false AS oauth_cimd_enabled,
            NULLIF(a.auth_template, '{{}}'::jsonb) AS header_template,
            coalesce(g.users_can_manage_policies, true)
                AS users_can_save_always_allow,
            -- Private: only the owner and the shares have access.
            false AS is_private,
            NULL::uuid AS owner_user_id,
            -- An app keeps its state: on is available, off is not.
            CASE WHEN NOT a.enabled THEN 'NOT_AVAILABLE' END
                AS organization_policy,
            a.created_at,
            a.updated_at
        FROM external_app a
        LEFT JOIN gated_app g ON g.external_app_id = a.id

        UNION ALL

        SELECT
            m.gated_app_id,
            CASE WHEN m.gated_app_id IS NULL THEN 0 END,
            'mcp',
            NULL,
            m.id,
            NULL,
            m.name,
            m.description,
            true,
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
            CASE WHEN m.auth_type = 'OAUTH' THEN
                CASE m.oauth_provider_mode
                    WHEN 'AUTO_DISCOVERY' THEN 'discovery'
                    ELSE 'manual'
                END
            END,
            m.oauth_authorization_endpoint,
            m.oauth_token_endpoint,
            CASE WHEN jsonb_typeof(m.oauth_scopes_override) = 'array' THEN
                ARRAY(
                    SELECT jsonb_array_elements_text(m.oauth_scopes_override)
                )::varchar[]
            END,
            m.oauth_additional_auth_params,
            -- The MCP OAuth flow always sends a PKCE challenge.
            true,
            m.oauth_cimd_enabled,
            NULL::jsonb,
            coalesce(m.users_can_manage_policies, true),
            NOT (
                m.is_public OR m.shared_with_basic OR m.owner_user_id IS NULL
            ),
            m.owner_user_id,
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
            'api',
            NULL,
            NULL,
            t.id,
            coalesce(nullif(t.display_name, ''), t.name),
            t.description,
            true,
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
            CASE WHEN o.id IS NOT NULL THEN 'manual' END,
            o.authorization_url,
            o.token_url,
            CASE WHEN jsonb_typeof(o.scopes) = 'array' THEN
                ARRAY(SELECT jsonb_array_elements_text(o.scopes))::varchar[]
            END,
            o.additional_params,
            o.supports_pkce,
            false,
            NULL,
            true,
            NOT (t.user_id IS NULL OR is_shared.value),
            t.user_id,
            CASE WHEN is_default.value THEN 'DEFAULT' END,
            TIMESTAMPTZ '{FALLBACK_CREATED_AT}',
            TIMESTAMPTZ '{FALLBACK_CREATED_AT}'
        FROM openapi_tool t
        LEFT JOIN oauth_config o ON o.id = t.oauth_config_id
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
    -- An integration of the organization is Available unless its source
    -- gives another setting. Each other integration is private.
    SELECT
        CASE
            WHEN is_private THEN 'NOT_AVAILABLE'
            ELSE coalesce(organization_policy, 'AVAILABLE')
        END AS installation_policy,
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

_INSERT_INTEGRATIONS = """
    INSERT INTO integration (
        id, kind, name, description, owner_user_id, installation_policy,
        enabled, auth_mode, auth_method, header_template,
        users_can_save_always_allow, mcp_server_id, external_app_id, tool_id,
        created_at, updated_at
    )
    SELECT
        id, kind, name, description, owner_user_id, installation_policy,
        enabled, auth_mode, auth_method, header_template,
        users_can_save_always_allow, mcp_server_id, external_app_id, tool_id,
        created_at, updated_at
    FROM integration_source
"""

# The client settings of each OAuth integration, with no secret.
_INSERT_OAUTH_CLIENTS = """
    INSERT INTO integration_oauth_client (
        integration_id, provider_mode, authorization_url, token_url, scopes,
        additional_params, pkce, cimd_enabled, created_at, updated_at
    )
    SELECT
        id, oauth_provider_mode,
        CASE WHEN oauth_provider_mode <> 'preset' THEN oauth_authorization_url END,
        CASE WHEN oauth_provider_mode <> 'preset' THEN oauth_token_url END,
        oauth_scopes, oauth_additional_params, oauth_pkce, oauth_cimd_enabled,
        created_at, updated_at
    FROM integration_source
    WHERE auth_method = 'oauth2'
"""

# Each MCP tool row. The actions of an OpenAPI spec and of a provider catalog
# need app code to read, so the app writes them.
_INSERT_MCP_ACTIONS = """
    INSERT INTO integration_action (
        integration_id, key, source, display_name, description, read_only,
        input_schema, output_schema, created_at, updated_at
    )
    SELECT
        src.id, t.name, 'mcp', coalesce(nullif(t.display_name, ''), t.name),
        t.description, t.mcp_read_only, t.mcp_input_schema,
        t.mcp_output_schema, src.created_at, src.updated_at
    FROM integration_source src
    JOIN tool t ON t.mcp_server_id = src.mcp_server_id
    ORDER BY src.id, t.id
    ON CONFLICT DO NOTHING
"""

# Credentials. The old columns use the same encryption as the new ones, so
# each secret is copied as its bytes, never decrypted. legacy_format names
# the old format, which the credential code reads. The header template of a
# per-user API key MCP server is in its encrypted admin config, so the app
# copies it.

# The configuration of an MCP server that the admin set up.
_INSERT_MCP_ORGANIZATION_CONNECTIONS = """
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, status,
        created_at, updated_at
    )
    SELECT i.id, NULL, c.config, 'mcp_config', 'connected',
        c.created_at, c.updated_at
    FROM integration i
    JOIN mcp_server m ON m.id = i.mcp_server_id
    JOIN mcp_connection_config c ON c.id = m.admin_connection_config_id
    ORDER BY i.id
    ON CONFLICT DO NOTHING
"""

# The configuration of each user, keyed by email today. A user row is made
# only when exactly one active user has that email; the newest wins.
_INSERT_MCP_USER_CONNECTIONS = """
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, status,
        created_at, updated_at
    )
    SELECT DISTINCT ON (i.id, u.id)
        i.id, u.id, c.config, 'mcp_config', 'connected',
        c.created_at, c.updated_at
    FROM mcp_connection_config c
    JOIN mcp_server m ON m.id = c.mcp_server_id
    JOIN integration i ON i.mcp_server_id = m.id
    JOIN "user" u ON lower(u.email) = lower(c.user_email) AND u.is_active
    WHERE c.id IS DISTINCT FROM m.admin_connection_config_id
      AND (
          SELECT count(*) FROM "user" o
          WHERE lower(o.email) = lower(c.user_email) AND o.is_active
      ) = 1
    ORDER BY i.id, u.id, c.updated_at DESC, c.id DESC
    ON CONFLICT DO NOTHING
"""

# The OAuth client of an MCP server is inside the admin configuration.
_SET_MCP_OAUTH_REGISTRATIONS = """
    UPDATE integration_oauth_client o
    SET registration = c.config, legacy_format = 'mcp_config'
    FROM integration i
    JOIN mcp_server m ON m.id = i.mcp_server_id
    JOIN mcp_connection_config c ON c.id = m.admin_connection_config_id
    WHERE o.integration_id = i.id
"""

# A built-in app holds its OAuth client in the organization credentials.
_SET_EXTERNAL_APP_OAUTH_REGISTRATIONS = """
    UPDATE integration_oauth_client o
    SET registration = a.organization_credentials,
        legacy_format = 'external_app_org'
    FROM integration i
    JOIN external_app a ON a.id = i.external_app_id
    WHERE o.integration_id = i.id AND a.app_type <> 'CUSTOM'
"""

# A custom app with a header template: the values the organization filled.
# In individual mode they are only the defaults that a user's values override.
_INSERT_EXTERNAL_APP_ORGANIZATION_CONNECTIONS = """
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, status,
        created_at, updated_at
    )
    SELECT i.id, NULL, a.organization_credentials, 'external_app_org',
        'connected', a.created_at, a.updated_at
    FROM external_app a
    JOIN integration i ON i.external_app_id = a.id
    WHERE a.app_type = 'CUSTOM' AND i.auth_method = 'api_key'
    ORDER BY i.id
    ON CONFLICT DO NOTHING
"""

_INSERT_EXTERNAL_APP_USER_CONNECTIONS = """
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, granted_scopes,
        status, created_at, updated_at
    )
    SELECT i.id, c.user_id, c.user_credentials,
        'external_app_user', c.granted_scopes::varchar[], 'connected',
        c.created_at, c.updated_at
    FROM external_app_user_credential c
    JOIN integration i ON i.external_app_id = c.external_app_id
    JOIN "user" u ON u.id = c.user_id AND u.is_active
    ORDER BY i.id, c.user_id
    ON CONFLICT DO NOTHING
"""

# The OAuth token of each user for each OpenAPI tool of that OAuth config.
_INSERT_OAUTH_USER_CONNECTIONS = """
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, status,
        created_at, updated_at
    )
    SELECT i.id, k.user_id, k.token_data, 'oauth_user_token',
        'connected', k.created_at, k.updated_at
    FROM oauth_user_token k
    JOIN tool t ON t.oauth_config_id = k.oauth_config_id
    JOIN integration i ON i.tool_id = t.id
    JOIN "user" u ON u.id = k.user_id AND u.is_active
    ORDER BY i.id, k.user_id
    ON CONFLICT DO NOTHING
"""

# The headers of a shared OpenAPI tool are plain JSON today. The decrypt path
# of each edition reads plain UTF-8 bytes, so they are copied as such.
_INSERT_TOOL_HEADER_CONNECTIONS = f"""
    INSERT INTO integration_connection (
        integration_id, user_id, secret, legacy_format, status,
        created_at, updated_at
    )
    SELECT i.id, NULL, convert_to(t.custom_headers::text, 'UTF8'),
        'tool_headers', 'connected',
        TIMESTAMPTZ '{FALLBACK_CREATED_AT}', TIMESTAMPTZ '{FALLBACK_CREATED_AT}'
    FROM tool t
    JOIN integration i ON i.tool_id = t.id
    WHERE i.auth_method = 'api_key'
    ORDER BY i.id
    ON CONFLICT DO NOTHING
"""

# An OpenAPI tool that signs in with OAuth or the Onyx login and also sends
# static headers: the headers become literal values of the header template.
# The template reads {name} as a placeholder, so each brace is doubled and the
# value goes out unchanged.
_SET_TOOL_HEADER_TEMPLATES = """
    UPDATE integration i
    SET header_template = headers.value
    FROM tool t
    CROSS JOIN LATERAL (
        SELECT jsonb_object_agg(
            h ->> 'key',
            replace(replace(h ->> 'value', '{', '{{'), '}', '}}')
        ) AS value
        FROM jsonb_array_elements(t.custom_headers) h
        WHERE h ->> 'key' IS NOT NULL
    ) headers
    WHERE t.id = i.tool_id
      AND i.auth_method IN ('oauth2', 'onyx_login')
      AND jsonb_typeof(t.custom_headers) = 'array'
      AND headers.value IS NOT NULL
"""

# oauth_config holds the client in the same encrypted string format.
_SET_OPENAPI_OAUTH_CLIENTS = """
    UPDATE integration_oauth_client o
    SET client_id = c.client_id, client_secret = c.client_secret
    FROM integration i
    JOIN tool t ON t.id = i.tool_id
    JOIN oauth_config c ON c.id = t.oauth_config_id
    WHERE o.integration_id = i.id
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
        src.kind,
        -- An Always allow that was set for chat only: the server is not
        -- available in Craft. Each agent keeps it; no admin value is made.
        t.enabled AND EXISTS (
            SELECT 1
            FROM workspace_action_policy w
            JOIN mcp_server m ON m.id = src.mcp_server_id
            WHERE w.gated_app_id = src.gated_app_id
              AND w.action_id = t.name
              AND w.policy = 'ALWAYS'
              AND NOT m.available_in_craft
        ) AS chat_only_allow
    FROM integration_source src
    JOIN tool t
      ON t.id = src.tool_id OR t.mcp_server_id = src.mcp_server_id
"""

# A private MCP server keeps its people. Basic makes the server public, and
# the access rule counts no default group, so a share with Admin becomes a
# share with each member of Admin.
_INSERT_MCP_USER_SHARES = """
    INSERT INTO integration__user (integration_id, user_id, permission, created_at)
    SELECT src.id, su.user_id, 'VIEWER', src.created_at
    FROM integration_source src
    JOIN mcp_server__user su ON su.mcp_server_id = src.mcp_server_id
    WHERE src.installation_policy = 'NOT_AVAILABLE'
    UNION
    SELECT src.id, uug.user_id, 'VIEWER', src.created_at
    FROM integration_source src
    JOIN mcp_server__user_group sg ON sg.mcp_server_id = src.mcp_server_id
    JOIN user_group ug ON ug.id = sg.user_group_id AND ug.is_default
    JOIN user__user_group uug ON uug.user_group_id = ug.id
    WHERE src.installation_policy = 'NOT_AVAILABLE'
      AND uug.user_id IS NOT NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_MCP_GROUP_SHARES = """
    INSERT INTO integration__user_group
        (integration_id, user_group_id, permission, installation_policy,
         created_at)
    SELECT src.id, sg.user_group_id, 'VIEWER', NULL, src.created_at
    FROM integration_source src
    JOIN mcp_server__user_group sg ON sg.mcp_server_id = src.mcp_server_id
    JOIN user_group ug ON ug.id = sg.user_group_id AND NOT ug.is_default
    WHERE src.installation_policy = 'NOT_AVAILABLE'
"""

# In the last release, each user of a custom agent used a private MCP server
# through the agent. An integration gives its own access, so this one-time
# copy gives those users a share. The users of an agent are the users that
# the agent access rule gives it to: its owner and the members of its owner
# group, and, while it is listed, its shares and (if public) each user. An
# agent with only tools that the admin did not select gave no use of the
# server.
_PRIVATE_MCP_AGENTS = """
    SELECT DISTINCT p.id AS persona_id, p.user_id, p.owner_group_id,
        p.is_public, p.is_listed, i.id AS integration_id, i.created_at
    FROM persona p
    JOIN persona__tool pt ON pt.persona_id = p.id
    JOIN tool t ON t.id = pt.tool_id AND t.enabled
    JOIN integration i ON i.mcp_server_id = t.mcp_server_id
    WHERE NOT p.deleted AND p.id <> 0
      AND i.installation_policy = 'NOT_AVAILABLE'
"""

# The groups of an agent: its owner group and, while it is listed, its group
# shares.
_PRIVATE_MCP_AGENT_GROUPS = f"""
    SELECT a.integration_id, a.created_at, a.owner_group_id AS user_group_id
    FROM ({_PRIVATE_MCP_AGENTS}) a
    WHERE a.owner_group_id IS NOT NULL
    UNION
    SELECT a.integration_id, a.created_at, pg.user_group_id
    FROM ({_PRIVATE_MCP_AGENTS}) a
    JOIN persona__user_group pg ON pg.persona_id = a.persona_id
    WHERE a.is_listed
"""

# A default group becomes its members, as for the shares of the server.
_INSERT_AGENT_USER_SHARES = f"""
    INSERT INTO integration__user (integration_id, user_id, permission, created_at)
    SELECT a.integration_id, a.user_id, 'VIEWER', a.created_at
    FROM ({_PRIVATE_MCP_AGENTS}) a
    WHERE a.user_id IS NOT NULL
    UNION
    SELECT a.integration_id, pu.user_id, 'VIEWER', a.created_at
    FROM ({_PRIVATE_MCP_AGENTS}) a
    JOIN persona__user pu ON pu.persona_id = a.persona_id
    WHERE a.is_listed AND pu.user_id IS NOT NULL
    UNION
    SELECT g.integration_id, uug.user_id, 'VIEWER', g.created_at
    FROM ({_PRIVATE_MCP_AGENT_GROUPS}) g
    JOIN user_group ug ON ug.id = g.user_group_id AND ug.is_default
    JOIN user__user_group uug ON uug.user_group_id = ug.id
    WHERE uug.user_id IS NOT NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_AGENT_GROUP_SHARES = f"""
    INSERT INTO integration__user_group
        (integration_id, user_group_id, permission, installation_policy,
         created_at)
    SELECT g.integration_id, g.user_group_id, 'VIEWER', NULL, g.created_at
    FROM ({_PRIVATE_MCP_AGENT_GROUPS}) g
    JOIN user_group ug ON ug.id = g.user_group_id AND NOT ug.is_default
    ON CONFLICT DO NOTHING
"""

# Each user could use a public agent, so its servers become Available. This
# runs after the share statements: they read the private servers.
_PUBLISH_PUBLIC_AGENT_INTEGRATIONS = f"""
    UPDATE integration i
    SET installation_policy = 'AVAILABLE'
    FROM ({_PRIVATE_MCP_AGENTS}) a
    WHERE a.integration_id = i.id AND a.is_public AND a.is_listed
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
    WHERE ti.kind = 'mcp' AND NOT t.enabled
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
    LEFT JOIN integration_source src ON src.id = w.gated_app_id
    LEFT JOIN mcp_server m ON m.id = src.mcp_server_id
    -- An admin value applies in chat and in Craft. Always allow on a server
    -- that is not available in Craft was set for chat only, so it goes to
    -- the agent links (chat_only_allow), not here.
    WHERE NOT (w.policy = 'ALWAYS' AND m.available_in_craft IS FALSE)
    ORDER BY w.gated_app_id, w.action_id
    ON CONFLICT DO NOTHING
"""

# Chat runs a custom tool with no question today. The default row of the
# organization keeps that for each operation of an OpenAPI integration.
_INSERT_OPENAPI_DEFAULT_POLICIES = """
    INSERT INTO integration_action_policy
        (integration_id, action, user_id, policy, created_at, updated_at)
    SELECT src.id, '', NULL, 'allow', src.created_at, src.updated_at
    FROM integration_source src
    WHERE src.tool_id IS NOT NULL
    ORDER BY src.id
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
    INSERT INTO user_integration_preference
        (user_id, integration_id, enabled, enabled_at)
    SELECT p.user_id, src.id, p.enabled_in_chat, NULL::timestamptz
    FROM mcp_server_user_preference p
    JOIN integration_source src ON src.mcp_server_id = p.mcp_server_id
    UNION ALL
    SELECT p.user_id, src.id, p.enabled_in_chat, NULL::timestamptz
    FROM tool_user_preference p
    JOIN integration_source src ON src.tool_id = p.tool_id
"""

# An integration is off for the user on that agent when the user turned off
# each tool that the agent has of it. disabled_tool_ids does not change.
_SET_DISABLED_INTEGRATIONS = """
    UPDATE assistant__user_specific_config c
    SET disabled_integration_ids = off.ids
    FROM (
        SELECT assistant_id, user_id,
            array_agg(integration_id ORDER BY integration_id) AS ids
        FROM (
            SELECT cfg.assistant_id, cfg.user_id, ti.integration_id
            FROM assistant__user_specific_config cfg
            JOIN persona__tool pt ON pt.persona_id = cfg.assistant_id
            JOIN tool_integration ti ON ti.tool_id = pt.tool_id
            GROUP BY cfg.assistant_id, cfg.user_id, ti.integration_id
            HAVING bool_and(pt.tool_id = ANY(cfg.disabled_tool_ids))
        ) per_integration
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

# An agent keeps the MCP tools it has (inherit, or allow for a bot agent and
# for a chat-only Always allow).
# Each other tool, now or added later, is blocked by the default. An agent
# with a custom tool gets empty settings, or allow for a bot agent.
_INSERT_PERSONA_LINKS = f"""
    INSERT INTO persona__integration
        (persona_id, integration_id, action_settings)
    SELECT
        pt.persona_id,
        ti.integration_id,
        CASE
            WHEN ti.kind = 'mcp' THEN jsonb_build_object(
                'default', 'blocked',
                'actions', jsonb_object_agg(
                    ti.tool_name,
                    CASE WHEN bot.persona_id IS NOT NULL OR ti.chat_only_allow
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
    WHERE NOT (pt.persona_id = 0 AND ti.kind = 'api' AND NOT t.enabled)
    GROUP BY pt.persona_id, ti.integration_id, ti.kind, bot.persona_id
"""

# A task keeps its pre-approvals. Each other action asks, as it does today
# for a task with no saved choice.
_INSERT_TASK_LINKS = f"""
    INSERT INTO scheduled_task__integration
        (scheduled_task_id, integration_id, action_settings)
    SELECT
        e.scheduled_task_id,
        src.id,
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

# Run after the commit, one table at a time; a rerun skips the rows it set.
_SET_RECORD_INTEGRATIONS = """
    UPDATE {table} SET integration_id = gated_app_id
    WHERE gated_app_id IS NOT NULL AND integration_id IS NULL
"""

# The old tool selection of a chat as tool options. A built-in tool stays a
# capability. An MCP tool becomes its action in the integration of its server,
# and an OpenAPI tool its whole integration. A deleted tool is left out. Run
# after the commit, in the transaction that drops tool_selection.
_FILL_TOOL_OPTIONS = """
    UPDATE chat_session c
    SET tool_options = jsonb_build_object(
        'allowed',
        CASE WHEN jsonb_typeof(c.tool_selection -> 'allowed_tool_ids') = 'array'
        THEN (
            SELECT coalesce(jsonb_agg(entry.value ORDER BY selected.n), '[]')
            FROM jsonb_array_elements_text(c.tool_selection -> 'allowed_tool_ids')
                WITH ORDINALITY AS selected(tool_id, n)
            JOIN tool t ON t.id = selected.tool_id::integer
            LEFT JOIN integration i
              ON i.mcp_server_id = t.mcp_server_id OR i.tool_id = t.id
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN t.in_code_tool_id IS NOT NULL THEN jsonb_build_object(
                        'type', 'capability', 'tool_id', t.id
                    )
                    WHEN i.mcp_server_id IS NOT NULL THEN jsonb_build_object(
                        'type', 'integration', 'integration_id', i.id,
                        'actions', jsonb_build_array(t.name)
                    )
                    WHEN i.tool_id IS NOT NULL THEN jsonb_build_object(
                        'type', 'integration', 'integration_id', i.id
                    )
                END AS value
            ) entry
            WHERE entry.value IS NOT NULL
        )
        END,
        'preferred',
        (
            SELECT CASE
                WHEN t.in_code_tool_id IS NOT NULL THEN jsonb_build_object(
                    'type', 'capability', 'tool_id', t.id
                )
                WHEN i.mcp_server_id IS NOT NULL THEN jsonb_build_object(
                    'type', 'action', 'integration_id', i.id,
                    'action', t.name
                )
            END
            FROM tool t
            LEFT JOIN integration i ON i.mcp_server_id = t.mcp_server_id
            WHERE t.id = (c.tool_selection ->> 'preferred_tool_id')::integer
        ),
        'internal_search_filters',
        c.tool_selection -> 'internal_search_filters'
    )
    WHERE c.tool_options IS NULL
      AND jsonb_typeof(c.tool_selection) = 'object'
"""


def _copy_integrations() -> None:
    for statement in (
        _CREATE_SOURCES,
        _INSERT_INTEGRATIONS,
        _SET_INTEGRATION_SEQUENCE,
        _INSERT_OAUTH_CLIENTS,
        _INSERT_MCP_ORGANIZATION_CONNECTIONS,
        _INSERT_MCP_USER_CONNECTIONS,
        _SET_MCP_OAUTH_REGISTRATIONS,
        _SET_EXTERNAL_APP_OAUTH_REGISTRATIONS,
        _INSERT_EXTERNAL_APP_ORGANIZATION_CONNECTIONS,
        _INSERT_EXTERNAL_APP_USER_CONNECTIONS,
        _INSERT_OAUTH_USER_CONNECTIONS,
        _INSERT_TOOL_HEADER_CONNECTIONS,
        _SET_TOOL_HEADER_TEMPLATES,
        _SET_OPENAPI_OAUTH_CLIENTS,
        _INSERT_MCP_ACTIONS,
        _CREATE_TOOL_INTEGRATIONS,
        _INSERT_MCP_USER_SHARES,
        _INSERT_MCP_GROUP_SHARES,
        _INSERT_AGENT_USER_SHARES,
        _INSERT_AGENT_GROUP_SHARES,
        _PUBLISH_PUBLIC_AGENT_INTEGRATIONS,
        _INSERT_UNSELECTED_MCP_TOOLS,
        _INSERT_ADMIN_POLICIES,
        _INSERT_OPENAPI_DEFAULT_POLICIES,
        _INSERT_USER_POLICIES,
        _INSERT_PREFERENCES,
        _INSERT_PERSONA_LINKS,
        _INSERT_TASK_LINKS,
    ):
        op.execute(statement)


def _legacy_key() -> bytes | None:
    # The key only decrypts existing rows. No seeded value depends on it.
    secret = os.environ.get("ENCRYPTION_KEY_SECRET")  # migration-determinism: allow
    encoded = (secret or "").encode()
    for size in _LEGACY_KEY_SIZES:
        if len(encoded) >= size:
            return encoded[:size]
    return None


def _envelope_keys(legacy_key: bytes | None) -> dict[str, bytes]:
    keys_json = os.environ.get("ENCRYPTION_KEYS", "")  # migration-determinism: allow
    keys_json = keys_json.strip()
    keys = {
        key_id: base64.b64decode(encoded, validate=True)
        for key_id, encoded in (json.loads(keys_json) if keys_json else {}).items()
    }
    if legacy_key is not None:
        keys[_LEGACY_KEY_ID] = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_LEGACY_ENVELOPE_KEY_INFO,
        ).derive(legacy_key)
    return keys


def _decrypt(data: bytes, keys: dict[str, bytes], legacy_key: bytes | None) -> str:
    if data.startswith(_ENVELOPE_MAGIC):
        fixed_length = len(_ENVELOPE_MAGIC) + 2
        if data[len(_ENVELOPE_MAGIC)] != _ENVELOPE_VERSION:
            raise ValueError("unknown envelope version")
        header_length = fixed_length + data[len(_ENVELOPE_MAGIC) + 1]
        key = keys[data[fixed_length:header_length].decode("ascii")]
        nonce_end = header_length + _NONCE_BYTES
        return (
            AESGCM(key)
            .decrypt(
                data[header_length:nonce_end], data[nonce_end:], data[:header_length]
            )
            .decode()
        )
    if legacy_key is not None:
        decryptor = Cipher(
            algorithms.AES(legacy_key), modes.CBC(data[:_CBC_IV_BYTES])
        ).decryptor()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        try:
            padded = decryptor.update(data[_CBC_IV_BYTES:]) + decryptor.finalize()
            return (unpadder.update(padded) + unpadder.finalize()).decode()
        except (ValueError, UnicodeDecodeError):
            # Values stored before the deployment had a key are plain text.
            pass
    return data.decode()


def _mcp_header_template(config: Any) -> dict[str, str] | None:
    """Old configs kept the template in ``headers``."""
    if not isinstance(config, dict):
        return None
    template = config.get("header_template") or config.get("headers")
    if not isinstance(template, dict):
        return None
    return {
        name: value
        for name, value in template.items()
        if isinstance(name, str)
        and isinstance(value, str)
        and name.lower() not in _DENYLISTED_HEADERS
    } or None


def _template_fields(template: dict[str, str]) -> list[dict[str, Any]] | None:
    """A secret field for each placeholder a person fills. Onyx fills
    ``user_email``."""
    keys: list[str] = []
    for value in template.values():
        for match in _TEMPLATE_TOKEN.finditer(value):
            key = match.group(1)
            if key is not None and key != "user_email" and key not in keys:
                keys.append(key)
    return [
        {"key": key, "label": key.replace("_", " "), "secret": True} for key in keys
    ] or None


def _copy_mcp_header_templates() -> None:
    """A config that does not read leaves no template, and the admin list
    shows the integration as not set up."""
    bind = op.get_bind()
    legacy_key = _legacy_key()
    keys = _envelope_keys(legacy_key)
    updates: list[dict[str, Any]] = []
    for row in bind.execute(
        sa.text(
            "SELECT i.id, c.config FROM integration i "
            "JOIN mcp_server m ON m.id = i.mcp_server_id "
            "JOIN mcp_connection_config c ON c.id = m.admin_connection_config_id "
            "WHERE i.auth_mode = 'individual' AND i.auth_method = 'api_key' "
            "AND i.header_template IS NULL "
            "ORDER BY i.id"
        )
    ):
        try:
            config = json.loads(_decrypt(bytes(row.config), keys, legacy_key))
        except Exception as error:
            logger.warning(
                "Integration %s: the MCP admin config does not read (%s)",
                row.id,
                type(error).__name__,
            )
            continue
        template = _mcp_header_template(config)
        if template is None:
            continue
        fields = _template_fields(template)
        updates.append(
            {
                "id": row.id,
                "header_template": json.dumps(template),
                "credential_fields": json.dumps(fields) if fields else None,
            }
        )
    if updates:
        bind.execute(
            sa.text(
                "UPDATE integration SET "
                "header_template = CAST(:header_template AS jsonb), "
                "credential_fields = CAST(:credential_fields AS jsonb) "
                "WHERE id = :id"
            ),
            updates,
        )


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The tables and the copy commit together. A retry after that commit skips
    # them and only validates.
    if not sa.inspect(bind).has_table("integration", schema=schema):
        # The foreign keys of integration lock mcp_server, external_app and
        # tool against writes while the tables are made.
        _with_bounded_lock_wait(_create_tables)
        _copy_integrations()
        _copy_mcp_header_templates()
        # The chat tables stay locked from here to the commit, so they are
        # altered last, with only the statement that needs a new column of
        # theirs after them.
        _with_bounded_lock_wait(_alter_old_tables)
        for statement in (
            _SET_DISABLED_INTEGRATIONS,
            "DROP TABLE tool_integration",
            "DROP TABLE integration_source",
        ):
            op.execute(statement)
    has_tool_selection = "tool_selection" in {
        column["name"]
        for column in sa.inspect(bind).get_columns("chat_session", schema=schema)
    }
    # Fill and validate only after the ALTER TABLE locks are released.
    bind.commit()
    quoted_schema = bind.dialect.identifier_preparer.quote_identifier(schema)
    # Each step commits on the migration connection, so env.py pins the tenant
    # search_path at the start of every transaction.
    steps: list[list[str]] = []
    if has_tool_selection:
        steps.append(
            [
                _FILL_TOOL_OPTIONS,
                # A parked run saved before tool options continues with the
                # tools of its agent.
                f"UPDATE {quoted_schema}.chat_response_checkpoint "
                "SET state = state - 'tool_selection' "
                "WHERE state ? 'tool_selection'",
                f"ALTER TABLE {quoted_schema}.chat_session DROP COLUMN tool_selection",
            ]
        )
    for table in RECORD_TABLES:
        steps.append(
            [_SET_RECORD_INTEGRATIONS.format(table=f"{quoted_schema}.{table}")]
        )
        steps.append(
            [
                f"ALTER TABLE {quoted_schema}.{table} "
                f"VALIDATE CONSTRAINT fk_{table}_integration_id"
            ]
        )
    for statements in steps:
        bind.exec_driver_sql(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        for statement in statements:
            bind.exec_driver_sql(statement)
        bind.commit()


def downgrade() -> None:
    # An approval made after the upgrade with no gated_app cannot stay.
    op.execute("DELETE FROM approval_request WHERE gated_app_id IS NULL")
    op.alter_column(
        "approval_request", "gated_app_id", existing_type=sa.Integer(), nullable=False
    )
    op.drop_column("assistant__user_specific_config", "disabled_integration_ids")
    for table in reversed(RECORD_TABLES):
        op.drop_column(table, "integration_id")
    op.add_column(
        "chat_session",
        sa.Column("tool_selection", postgresql.JSONB(), nullable=True),
    )
    op.execute(
        "UPDATE chat_response_checkpoint SET state = state - 'tool_options' "
        "WHERE state ? 'tool_options'"
    )
    op.drop_column("chat_session", "tool_options")
    for table in (
        "scheduled_task__integration",
        "persona__integration",
        "user_integration_preference",
        "integration__user_group",
        "integration__user",
        "integration_action_policy",
        "integration_connection",
        "integration_oauth_client",
        "integration_action",
    ):
        op.drop_table(table)
    op.drop_table("integration")
