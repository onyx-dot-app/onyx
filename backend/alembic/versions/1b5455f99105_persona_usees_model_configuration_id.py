"""Persona uses model configuration id

Revision ID: 1b5455f99105
Revises: e7f8a9b0c1d2
Create Date: 2026-01-27 19:11:34.510574

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1b5455f99105"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # We need to migrate from llm_model_provider_override and llm_model_version_override to default_model_configuration_id
    # Migration Strategy:
    # 1. Port over where provider_override + model_version are both present
    # 2. Port over where only provider is present (Provider default)
    # 3. Where only the model is provided, or neither provider or model are provided, we go for global default

    conn = op.get_bind()

    # Strategy 1: Both provider_override and model_version are present
    # Match against model_configuration using provider name and model name
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET default_model_configuration_id = mc.id
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
            SET default_model_configuration_id = mc.id
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.llm_model_provider_override IS NOT NULL
              AND persona.llm_model_version_override IS NULL
              AND persona.default_model_configuration_id IS NULL
              AND lp.name = persona.llm_model_provider_override
              AND mc.name = lp.default_model_name
        """
        )
    )

    # For remaining personas with only model set but no match found,
    # fall back to global default (provider's default model where is_default_provider = true)
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET default_model_configuration_id = mc.id
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.llm_model_provider_override IS NULL
              AND persona.llm_model_version_override IS NOT NULL
              AND persona.default_model_configuration_id IS NULL
              AND lp.is_default_provider = true
              AND mc.name = lp.default_model_name
        """
        )
    )


def downgrade() -> None:
    # Migrate data back from default_model_configuration_id to old columns
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET llm_model_provider_override = lp.name,
                llm_model_version_override = mc.name
            FROM model_configuration mc
            JOIN llm_provider lp ON mc.llm_provider_id = lp.id
            WHERE persona.default_model_configuration_id IS NOT NULL
              AND persona.default_model_configuration_id = mc.id
        """
        )
    )
