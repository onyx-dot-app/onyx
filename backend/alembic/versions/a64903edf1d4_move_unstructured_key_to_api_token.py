"""move the Unstructured key to api_token

Revision ID: a64903edf1d4
Revises: 04fc892ede01
Create Date: 2026-10-16 03:00:00.000000

The Unstructured key lived in plaintext in the key-value store. It is
encrypted into an api_token row through ``onyx.utils.encryption`` (as
revision ``1e0a3e4226f7`` does), and the store keeps only the token id,
under a new key, so a stale cache of the old value is never read.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "a64903edf1d4"
down_revision = "04fc892ede01"
branch_labels = None
depends_on = None

_OLD_UNSTRUCTURED_KEY = "unstructured_api_key"
_NEW_UNSTRUCTURED_KEY = "unstructured_api_token_id"


def upgrade() -> None:
    conn = op.get_bind()
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
