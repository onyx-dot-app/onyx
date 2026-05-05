"""optional_provider_name_persona_id_override

Revision ID: e3bcc6cbe3bf
Revises: 74379b447d4c
Create Date: 2026-05-05 10:33:13.148334

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e3bcc6cbe3bf"
down_revision = "74379b447d4c"
branch_labels = None
depends_on = None

# Lightweight table references for DML — avoids importing ORM models.
persona_table = sa.table(
    "persona",
    sa.column("llm_model_provider_override", sa.String),
    sa.column("llm_model_version_override", sa.String),
    sa.column("default_model_configuration_id", sa.Integer),
)

llm_provider_table = sa.table(
    "llm_provider",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("provider", sa.String),
)

model_configuration_table = sa.table(
    "model_configuration",
    sa.column("id", sa.Integer),
    sa.column("llm_provider_id", sa.Integer),
    sa.column("name", sa.String),
)


def upgrade() -> None:
    # 1. Make llm_provider.name nullable and drop the unique constraint so that
    #    the display name is no longer the unique identifier for a provider.
    op.alter_column("llm_provider", "name", nullable=True)
    op.drop_constraint("llm_provider_name_key", "llm_provider", type_="unique")

    # 2. Data migration: populate default_model_configuration_id from the existing
    #    string pair (llm_model_provider_override, llm_model_version_override).
    #    default_model_configuration_id was added by a prior migration but never
    #    written to — this backfills it for all pre-existing personas.
    #    Rows with no match (provider/model deleted or mismatched) stay NULL and
    #    fall back to the default provider at runtime.
    #
    #    Referencing llm_provider_table and model_configuration_table in the WHERE
    #    clause causes the PostgreSQL dialect to emit an UPDATE … FROM … clause.
    op.execute(
        sa.update(persona_table)
        .values(default_model_configuration_id=model_configuration_table.c.id)
        .where(
            persona_table.c.llm_model_provider_override == llm_provider_table.c.name,
            persona_table.c.llm_model_version_override
            == model_configuration_table.c.name,
            model_configuration_table.c.llm_provider_id == llm_provider_table.c.id,
            persona_table.c.llm_model_provider_override.is_not(None),
            persona_table.c.llm_model_version_override.is_not(None),
            persona_table.c.default_model_configuration_id.is_(None),
        )
    )


def downgrade() -> None:
    # Backfill any null names with a unique fallback before re-adding the NOT NULL
    # and UNIQUE constraints.  Using provider + '-' + id avoids collisions when
    # multiple providers share the same provider type string.
    op.execute(
        sa.update(llm_provider_table)
        .where(llm_provider_table.c.name.is_(None))
        .values(
            name=llm_provider_table.c.provider
            + sa.literal("-")
            + sa.cast(llm_provider_table.c.id, sa.Text)
        )
    )
    op.create_unique_constraint("llm_provider_name_key", "llm_provider", ["name"])
    op.alter_column("llm_provider", "name", nullable=False)
