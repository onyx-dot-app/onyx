"""seed_exa_provider_from_env

Revision ID: 3c9a65f1207f
Revises: 1f2a3b4c5d6e
Create Date: 2025-11-20 19:18:00.000000

"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.utils.encryption import encrypt_string_to_bytes

revision = "3c9a65f1207f"
down_revision = "1f2a3b4c5d6e"
branch_labels = None
depends_on = None


EXA_PROVIDER_NAME = "Exa (auto-imported)"


def _get_internet_search_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "internet_search_provider",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("provider_type", sa.String),
        sa.Column("api_key", sa.LargeBinary),
        sa.Column("config", postgresql.JSONB),
        sa.Column("is_active", sa.Boolean),
    )


def upgrade() -> None:
    exa_api_key = os.environ.get("EXA_API_KEY")
    if not exa_api_key:
        return

    bind = op.get_bind()
    metadata = sa.MetaData()
    table = _get_internet_search_table(metadata)

    existing = bind.execute(
        sa.select(table.c.id).where(table.c.name == EXA_PROVIDER_NAME)
    ).first()
    if existing:
        return

    encrypted_key = encrypt_string_to_bytes(exa_api_key)

    has_active_provider = bind.execute(
        sa.select(table.c.id).where(table.c.is_active.is_(True))
    ).first()

    bind.execute(
        table.insert().values(
            name=EXA_PROVIDER_NAME,
            provider_type="exa",
            api_key=encrypted_key,
            config=None,
            is_active=not bool(has_active_provider),
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    table = _get_internet_search_table(metadata)

    bind.execute(table.delete().where(table.c.name == EXA_PROVIDER_NAME))
