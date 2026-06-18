"""drop_persona_llm_override_strings

Drop the legacy llm_model_provider_override and llm_model_version_override string
columns from persona now that all reads/writes use default_model_configuration_id.
Deferred from a5370af8f8a0 for a staged rollout.

Revision ID: b6c7d8e9f0a1
Revises: a5370af8f8a0
Create Date: 2026-05-05

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "a5370af8f8a0"
branch_labels = None
depends_on = None

# Lightweight table references for the downgrade backfill.
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
    op.drop_column("persona", "llm_model_provider_override")
    op.drop_column("persona", "llm_model_version_override")


def downgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("llm_model_provider_override", sa.String(), nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column("llm_model_version_override", sa.String(), nullable=True),
    )

    # Best-effort restore of provider name + model name from the FK.
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
