"""add api_token table

Revision ID: eb0c14780dc5
Revises: c92b67e56ec4
Create Date: 2026-10-15 23:58:00.000000

Moves every admin-entered third-party API key into one ``api_token`` table.
Each feature row now points to a token by ``api_token_id`` instead of holding
its own encrypted copy, so a key can be reused and rotated in one place.

Each stored key becomes its own token row; nothing is merged. The encrypted
bytes are copied as they are, so no value is decrypted for the database
columns. The Unstructured key lived in plaintext in the key-value store, so it
is encrypted on the way in through ``onyx.utils.encryption`` (as revision
``1e0a3e4226f7`` does) and the store keeps only the token id, under a new key.
"""

from __future__ import annotations

import json
import os

from alembic import op
import sqlalchemy as sa

from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes
from shared_configs.configs import MULTI_TENANT

# revision identifiers, used by Alembic.
revision = "eb0c14780dc5"
down_revision = "c92b67e56ec4"
branch_labels = None
depends_on = None

_OLD_UNSTRUCTURED_KEY = "unstructured_api_key"
_NEW_UNSTRUCTURED_KEY = "unstructured_api_token_id"

# (table, primary key column, platform SQL, base URL SQL, extra row filter)
_CONSUMERS: list[tuple[str, str, str, str, str]] = [
    ("llm_provider", "id", "provider", "api_base", ""),
    ("voice_provider", "id", "provider_type", "api_base", ""),
    # The enum is stored by name (OPENAI), while every other table uses the
    # lowercase value, so the platforms line up across features.
    (
        "embedding_provider",
        "provider_type",
        "lower(provider_type::text)",
        "api_url",
        "",
    ),
    ("internet_search_provider", "id", "provider_type", "config->>'base_url'", ""),
    ("internet_content_provider", "id", "provider_type", "config->>'base_url'", ""),
    ("tracing_provider_config", "id", "provider_type", "NULL", ""),
    # A soft-deleted hook keeps no key: nothing reads it, and a token held by
    # a deleted row would look unused yet could never be deleted.
    ("hook", "id", "'hook'", "endpoint_url", "AND deleted = false"),
]

# Env vars holding the Onyx-owned keys Cloud gives new tenants. Keys saved
# from them before this revision must stay Onyx-owned (is_system), so tenant
# admins cannot list, reuse or rotate them.
_CLOUD_DEFAULT_KEY_ENV_VARS = (
    "OPENAI_DEFAULT_API_KEY",
    "ANTHROPIC_DEFAULT_API_KEY",
    "OPENROUTER_DEFAULT_API_KEY",
    "COHERE_DEFAULT_API_KEY",
)


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_token_platform", "api_token", ["platform"])

    conn = op.get_bind()
    for table, pk, platform_sql, base_url_sql, row_filter in _CONSUMERS:
        op.add_column(
            table,
            sa.Column(
                "api_token_id",
                sa.Integer(),
                sa.ForeignKey("api_token.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_api_token_id", table, ["api_token_id"])

        rows = conn.execute(
            sa.text(
                f"SELECT {pk}::text AS pk, {platform_sql} AS platform, "
                f"{base_url_sql} AS base_url, api_key FROM {table} "
                f"WHERE api_key IS NOT NULL {row_filter}"
            )
        ).fetchall()
        for row in rows:
            token_id = conn.execute(
                sa.text(
                    "INSERT INTO api_token (platform, value, base_url) "
                    "VALUES (:platform, :value, :base_url) RETURNING id"
                ),
                {
                    "platform": row.platform,
                    "value": row.api_key,
                    "base_url": row.base_url,
                },
            ).scalar_one()
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET api_token_id = :token_id "
                    f"WHERE {pk}::text = :pk"
                ),
                {"token_id": token_id, "pk": row.pk},
            )

        op.drop_column(table, "api_key")

    if MULTI_TENANT:
        _mark_cloud_default_keys(conn)

    stored = conn.execute(
        sa.text("SELECT value FROM key_value_store WHERE key = :key"),
        {"key": _OLD_UNSTRUCTURED_KEY},
    ).scalar_one_or_none()
    if isinstance(stored, str) and stored:
        # Encrypting uses a random IV. The row only exists where an
        # Unstructured key was already set, never in the template schema.
        token_id = conn.execute(  # migration-determinism: allow
            sa.text(
                "INSERT INTO api_token (platform, value) "
                "VALUES ('unstructured', :value) RETURNING id"
            ),
            {"value": encrypt_string_to_bytes(stored)},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO key_value_store (key, value) "
                "VALUES (:key, CAST(:value AS jsonb))"
            ),
            {"key": _NEW_UNSTRUCTURED_KEY, "value": json.dumps(token_id)},
        )
    conn.execute(
        sa.text("DELETE FROM key_value_store WHERE key = :key"),
        {"key": _OLD_UNSTRUCTURED_KEY},
    )


def _mark_cloud_default_keys(conn: sa.Connection) -> None:
    """Mark keys that match a Cloud default key as Onyx-owned."""
    # Reads the deployment's own keys to find matching rows; inserts nothing.
    defaults = {  # migration-determinism: allow
        value for name in _CLOUD_DEFAULT_KEY_ENV_VARS if (value := os.environ.get(name))
    }
    if not defaults:
        return
    rows = conn.execute(sa.text("SELECT id, value FROM api_token")).fetchall()
    system_ids = [
        row.id for row in rows if decrypt_bytes_to_string(bytes(row.value)) in defaults
    ]
    if system_ids:
        conn.execute(
            sa.text("UPDATE api_token SET is_system = true WHERE id = ANY(:ids)"),
            {"ids": system_ids},
        )


def downgrade() -> None:
    conn = op.get_bind()

    stored_id = conn.execute(
        sa.text("SELECT value FROM key_value_store WHERE key = :key"),
        {"key": _NEW_UNSTRUCTURED_KEY},
    ).scalar_one_or_none()
    if isinstance(stored_id, int):
        encrypted = conn.execute(
            sa.text("SELECT value FROM api_token WHERE id = :id"),
            {"id": stored_id},
        ).scalar_one_or_none()
        if encrypted is not None:
            conn.execute(
                sa.text(
                    "INSERT INTO key_value_store (key, value) "
                    "VALUES (:key, CAST(:value AS jsonb))"
                ),
                {
                    "key": _OLD_UNSTRUCTURED_KEY,
                    "value": json.dumps(decrypt_bytes_to_string(bytes(encrypted))),
                },
            )
    conn.execute(
        sa.text("DELETE FROM key_value_store WHERE key = :key"),
        {"key": _NEW_UNSTRUCTURED_KEY},
    )

    for table, _pk, _platform_sql, _base_url_sql, _row_filter in _CONSUMERS:
        op.add_column(table, sa.Column("api_key", sa.LargeBinary(), nullable=True))
        conn.execute(
            sa.text(
                f"UPDATE {table} SET api_key = api_token.value FROM api_token "
                f"WHERE {table}.api_token_id = api_token.id"
            )
        )
        op.drop_index(f"ix_{table}_api_token_id", table_name=table)
        op.drop_column(table, "api_token_id")

    op.drop_index("ix_api_token_platform", table_name="api_token")
    op.drop_table("api_token")
