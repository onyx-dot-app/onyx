"""move ollama api key from custom_config to api_key

Revision ID: 1e0a3e4226f7
Revises: fd006e57c868
Create Date: 2026-07-20 12:28:16.748159

Moves the optional Ollama Cloud bearer token out of the plaintext
``custom_config`` JSONB and into the encrypted ``api_key`` column, matching how
every other provider stores its credential.

Encryption goes through ``onyx.utils.encryption`` (as revisions ``0a98909f2757``
and ``3c9a65f1207f`` do) rather than a local reimplementation: that helper
dispatches on EE-vs-MIT, so the value we write is exactly what the running app
reads back. Reimplementing AES here would ignore that gate and corrupt values on
MIT deployments that happen to have ENCRYPTION_KEY_SECRET set (where the app
stores plaintext).

The downgrade restores ``custom_config.OLLAMA_API_KEY`` (what older code reads)
but deliberately leaves ``api_key`` in place rather than nulling it. Once
upgraded, a row with a set ``api_key`` is indistinguishable from one whose
``api_key`` predated this migration, so clearing it could wipe an unrelated
credential. Repopulating ``custom_config`` while keeping ``api_key`` is safe:
worst case a row ends up with the same key in both places, which is harmless.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "1e0a3e4226f7"
down_revision = "fd006e57c868"
branch_labels = None
depends_on = None


OLLAMA_PROVIDER = "ollama_chat"
OLLAMA_API_KEY_CONFIG_KEY = "OLLAMA_API_KEY"


def _llm_provider_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "llm_provider",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String),
        sa.Column("api_key", sa.LargeBinary),
        sa.Column("custom_config", postgresql.JSONB),
    )


def upgrade() -> None:
    bind = op.get_bind()
    table = _llm_provider_table(sa.MetaData())

    rows = bind.execute(
        sa.select(table.c.id, table.c.api_key, table.c.custom_config).where(
            table.c.provider == OLLAMA_PROVIDER
        )
    ).all()

    for row_id, api_key, custom_config in rows:
        if not custom_config or OLLAMA_API_KEY_CONFIG_KEY not in custom_config:
            continue

        stored_key = custom_config.get(OLLAMA_API_KEY_CONFIG_KEY)
        remaining_config = {
            k: v for k, v in custom_config.items() if k != OLLAMA_API_KEY_CONFIG_KEY
        }
        new_custom_config = remaining_config or None

        # Don't clobber an existing api_key; just drop the legacy config value.
        new_api_key = api_key
        if api_key is None and stored_key:
            new_api_key = encrypt_string_to_bytes(stored_key)

        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(api_key=new_api_key, custom_config=new_custom_config)
        )


def downgrade() -> None:
    bind = op.get_bind()
    table = _llm_provider_table(sa.MetaData())

    rows = bind.execute(
        sa.select(table.c.id, table.c.api_key, table.c.custom_config).where(
            table.c.provider == OLLAMA_PROVIDER
        )
    ).all()

    for row_id, api_key, custom_config in rows:
        if api_key is None:
            continue

        # Restore the legacy config value; leave api_key untouched so we never
        # clear a credential that may have predated this migration.
        new_custom_config = dict(custom_config or {})
        new_custom_config[OLLAMA_API_KEY_CONFIG_KEY] = decrypt_bytes_to_string(
            bytes(api_key)
        )

        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(custom_config=new_custom_config)
        )
