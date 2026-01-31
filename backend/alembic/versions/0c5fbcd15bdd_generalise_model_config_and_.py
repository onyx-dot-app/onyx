"""Generalise model config and differentiate via flow

Revision ID: 0c5fbcd15bdd
Revises: f220515df7b4
Create Date: 2026-01-26 14:43:16.932376

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0c5fbcd15bdd"
down_revision = "f220515df7b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add each model config to the text flow, setting the global default if it exists
    op.execute(
        """
        INSERT INTO flow_mapping (flow_type, is_default, model_configuration_id)
        SELECT
            'text' AS flow_type,
            COALESCE(
                (lp.is_default_provider IS TRUE AND lp.default_model_name = mc.name),
                FALSE
            ) AS is_default,
            mc.id AS model_configuration_id
        FROM model_configuration mc
        LEFT JOIN llm_provider lp
            ON lp.id = mc.llm_provider_id;
        """
    )

    # Add vision models to the vision flow
    op.execute(
        """
        INSERT INTO flow_mapping (flow_type, is_default, model_configuration_id)
        SELECT
            'vision' AS flow_type,
            COALESCE(
                (lp.is_default_vision_provider IS TRUE AND lp.default_vision_model = mc.name),
                FALSE
            ) AS is_default,
            mc.id AS model_configuration_id
        FROM model_configuration mc
        LEFT JOIN llm_provider lp
            ON lp.id = mc.llm_provider_id;
        """
    )


def downgrade() -> None:
    # Populate vision defaults from flow_mapping
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET
            is_default_vision_provider = TRUE,
            default_vision_model = mc.name
        FROM flow_mapping fm
        JOIN model_configuration mc ON mc.id = fm.model_configuration_id
        WHERE fm.flow_type = 'vision'
          AND fm.is_default = TRUE
          AND mc.llm_provider_id = lp.id;
        """
    )

    # Populate text defaults from flow_mapping
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET
            is_default_provider = TRUE,
            default_model_name = mc.name
        FROM flow_mapping fm
        JOIN model_configuration mc ON mc.id = fm.model_configuration_id
        WHERE fm.flow_type = 'text'
          AND fm.is_default = TRUE
          AND mc.llm_provider_id = lp.id;
        """
    )

    # For providers that have text flow mappings but aren't the default,
    # we still need a default_model_name (it was NOT NULL originally)
    # Pick the first visible model or any model for that provider
    op.execute(
        """
        UPDATE llm_provider AS lp
        SET default_model_name = (
            SELECT mc.name
            FROM model_configuration mc
            JOIN flow_mapping fm ON fm.model_configuration_id = mc.id
            WHERE mc.llm_provider_id = lp.id
              AND fm.flow_type = 'text'
            ORDER BY mc.is_visible DESC, mc.id ASC
            LIMIT 1
        )
        WHERE lp.default_model_name IS NULL;
        """
    )
