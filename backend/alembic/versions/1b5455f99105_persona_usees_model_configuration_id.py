"""Persona uses model configuration id

Revision ID: 1b5455f99105
Revises: 72aa7de2e5cf
Create Date: 2026-01-27 19:11:34.510574

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1b5455f99105"
down_revision = "72aa7de2e5cf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new model_configuration_id_override column with FK
    op.add_column(
        "persona",
        sa.Column("model_configuration_id_override", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_persona_model_configuration_id_override",
        "persona",
        "model_configuration",
        ["model_configuration_id_override"],
        ["id"],
        ondelete="SET NULL",
    )

    # We need to migrate from llm_model_provider_override and llm_model_version_override to model_configuration_id_override
    # Migration Strategy:
    # 1. Port over where provider_override + model_version are both present
    # 2. Port over where only provider is present (Provider default)
    # 3. Where only model is present, we attempt to find the model. Otherwise we go for global default

    conn = op.get_bind()

    # Strategy 1: Both provider_override and model_version are present
    # Match against model_configuration using provider name and model name
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET model_configuration_id_override = mc.id
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.llm_model_provider_override IS NOT NULL
              AND persona.llm_model_version_override IS NOT NULL
              AND lp.name = persona.llm_model_provider_override
              AND mc.name = persona.llm_model_version_override
        """
        )
    )

    # Strategy 2: Only provider is present (use Provider's default model)
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET model_configuration_id_override = mc.id
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.llm_model_provider_override IS NOT NULL
              AND persona.llm_model_version_override IS NULL
              AND persona.model_configuration_id_override IS NULL
              AND lp.name = persona.llm_model_provider_override
              AND mc.name = lp.default_model_name
        """
        )
    )

    # Strategy 3: Only model is present - try to find the model in any provider
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET model_configuration_id_override = (
                SELECT mc.id
                FROM model_configuration mc
                WHERE mc.name = persona.llm_model_version_override
                LIMIT 1
            )
            WHERE persona.llm_model_provider_override IS NULL
              AND persona.llm_model_version_override IS NOT NULL
              AND persona.model_configuration_id_override IS NULL
              AND EXISTS (
                  SELECT 1 FROM model_configuration mc
                  WHERE mc.name = persona.llm_model_version_override
              )
        """
        )
    )

    # For remaining personas with only model set but no match found,
    # fall back to global default (provider's default model where is_default_provider = true)
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET model_configuration_id_override = mc.id
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.llm_model_provider_override IS NULL
              AND persona.llm_model_version_override IS NOT NULL
              AND persona.model_configuration_id_override IS NULL
              AND lp.is_default_provider = true
              AND mc.name = lp.default_model_name
        """
        )
    )

    # Drop old columns
    op.drop_column("persona", "llm_model_provider_override")
    op.drop_column("persona", "llm_model_version_override")


def downgrade() -> None:
    # Re-add old columns
    op.add_column(
        "persona",
        sa.Column("llm_model_version_override", sa.String(), nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column("llm_model_provider_override", sa.String(), nullable=True),
    )

    # Drop FK constraint and new column
    op.drop_constraint(
        "fk_persona_model_configuration_id_override", "persona", type_="foreignkey"
    )
    op.drop_column("persona", "model_configuration_id_override")
