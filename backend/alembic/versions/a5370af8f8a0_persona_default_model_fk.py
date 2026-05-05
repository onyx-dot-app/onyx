"""persona_default_model_fk

Replace the deprecated (llm_model_provider_override, llm_model_version_override) string
pair on persona with the canonical default_model_configuration_id integer FK that was
added by a prior migration but never written to.

Revision ID: a5370af8f8a0
Revises: 74379b447d4c
Create Date: 2026-05-05

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a5370af8f8a0"
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
)

model_configuration_table = sa.table(
    "model_configuration",
    sa.column("id", sa.Integer),
    sa.column("llm_provider_id", sa.Integer),
    sa.column("name", sa.String),
)


def upgrade() -> None:
    # 1. Backfill default_model_configuration_id from the existing string pair.
    #    Rows with no match (provider/model deleted, names mismatched, or already
    #    NULL) are left NULL and will fall back to the global default at runtime.
    #
    #    Referencing llm_provider_table and model_configuration_table in the WHERE
    #    clause causes the PostgreSQL dialect to emit UPDATE … FROM.
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

    # 2. Drop the now-redundant string columns.
    op.drop_column("persona", "llm_model_provider_override")
    op.drop_column("persona", "llm_model_version_override")


def downgrade() -> None:
    # Re-add the string columns (nullable — old values are gone).
    op.add_column(
        "persona",
        sa.Column("llm_model_provider_override", sa.String(), nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column("llm_model_version_override", sa.String(), nullable=True),
    )

    # Best-effort backfill: restore provider name + model name from the FK.
    # Referencing llm_provider_table and model_configuration_table in the WHERE
    # clause causes the PostgreSQL dialect to emit UPDATE … FROM.
    op.execute(
        sa.update(persona_table)
        .values(
            llm_model_provider_override=llm_provider_table.c.name,
            llm_model_version_override=model_configuration_table.c.name,
        )
        .where(
            persona_table.c.default_model_configuration_id
            == model_configuration_table.c.id,
            model_configuration_table.c.llm_provider_id == llm_provider_table.c.id,
            persona_table.c.default_model_configuration_id.is_not(None),
        )
    )
