"""Populate flow mapping data

Revision ID: 01f8e6d95a33
Revises: d5c86e2c6dc6
Create Date: 2026-01-31 17:37:10.485558

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "01f8e6d95a33"
down_revision = "d5c86e2c6dc6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add each model config to the conversation flow.
    # Exclude models that are part of ImageGenerationConfig.
    # Use ON CONFLICT to make this migration idempotent in cases where startup logic
    # already backfilled rows before this migration runs.
    op.execute(
        """
        INSERT INTO llm_model_flow (llm_model_flow_type, is_default, model_configuration_id)
        SELECT
            'CHAT' AS llm_model_flow_type,
            COALESCE(
                (lp.is_default_provider IS TRUE AND lp.default_model_name = mc.name),
                FALSE
            ) AS is_default,
            mc.id AS model_configuration_id
        FROM model_configuration mc
        LEFT JOIN llm_provider lp
            ON lp.id = mc.llm_provider_id
        WHERE NOT EXISTS (
            SELECT 1 FROM image_generation_config igc
            WHERE igc.model_configuration_id = mc.id
        )
        ON CONFLICT (llm_model_flow_type, model_configuration_id) DO NOTHING;
        """
    )

    # Add models with supports_image_input to the vision flow.
    op.execute(
        """
        INSERT INTO llm_model_flow (llm_model_flow_type, is_default, model_configuration_id)
        SELECT
            'VISION' AS llm_model_flow_type,
            COALESCE(
                (lp.is_default_vision_provider IS TRUE AND lp.default_vision_model = mc.name),
                FALSE
            ) AS is_default,
            mc.id AS model_configuration_id
        FROM model_configuration mc
        LEFT JOIN llm_provider lp
            ON lp.id = mc.llm_provider_id
        WHERE mc.supports_image_input IS TRUE
        ON CONFLICT (llm_model_flow_type, model_configuration_id) DO NOTHING;
        """
    )

    # Recompute defaults from legacy provider flags so values are correct even if rows
    # already existed before this migration.
    op.execute(
        """
        UPDATE llm_model_flow
        SET is_default = FALSE
        WHERE llm_model_flow_type IN ('CHAT', 'VISION');
        """
    )

    op.execute(
        """
        UPDATE llm_model_flow AS mf
        SET is_default = TRUE
        FROM model_configuration mc
        JOIN llm_provider lp ON lp.id = mc.llm_provider_id
        WHERE mf.model_configuration_id = mc.id
          AND mf.llm_model_flow_type = 'CHAT'
          AND lp.is_default_provider IS TRUE
          AND lp.default_model_name = mc.name
          AND NOT EXISTS (
              SELECT 1 FROM image_generation_config igc
              WHERE igc.model_configuration_id = mc.id
          );
        """
    )

    op.execute(
        """
        UPDATE llm_model_flow AS mf
        SET is_default = TRUE
        FROM model_configuration mc
        JOIN llm_provider lp ON lp.id = mc.llm_provider_id
        WHERE mf.model_configuration_id = mc.id
          AND mf.llm_model_flow_type = 'VISION'
          AND mc.supports_image_input IS TRUE
          AND lp.is_default_vision_provider IS TRUE
          AND lp.default_vision_model = mc.name;
        """
    )


def downgrade() -> None:
    # Populate vision defaults from model_flow
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET
            is_default_vision_provider = TRUE,
            default_vision_model = mc.name
        FROM llm_model_flow mf
        JOIN model_configuration mc ON mc.id = mf.model_configuration_id
        WHERE mf.llm_model_flow_type = 'VISION'
          AND mf.is_default = TRUE
          AND mc.llm_provider_id = lp.id;
        """
    )

    # Populate conversation defaults from model_flow
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET
            is_default_provider = TRUE,
            default_model_name = mc.name
        FROM llm_model_flow mf
        JOIN model_configuration mc ON mc.id = mf.model_configuration_id
        WHERE mf.llm_model_flow_type = 'CHAT'
          AND mf.is_default = TRUE
          AND mc.llm_provider_id = lp.id;
        """
    )

    # For providers that have conversation flow mappings but aren't the default,
    # we still need a default_model_name (it was NOT NULL originally)
    # Pick the first visible model or any model for that provider
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET default_model_name = (
            SELECT mc.name
            FROM model_configuration mc
            JOIN llm_model_flow mf ON mf.model_configuration_id = mc.id
            WHERE mc.llm_provider_id = lp.id
              AND mf.llm_model_flow_type = 'CHAT'
            ORDER BY mc.is_visible DESC, mc.id ASC
            LIMIT 1
        )
        WHERE lp.default_model_name IS NULL;
        """
    )

    # Delete all model_flow entries (reverse the inserts from upgrade)
    op.execute("DELETE FROM llm_model_flow;")
