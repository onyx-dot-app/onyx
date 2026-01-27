"""Generalise model config and differentiate via flow

Revision ID: 0c5fbcd15bdd
Revises: 41fa44bef321
Create Date: 2026-01-26 14:43:16.932376

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.enums import ModelFlowType

# revision identifiers, used by Alembic.
revision = "0c5fbcd15bdd"
down_revision = "41fa44bef321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Flow Mapping Migration + Creation
    # Create Flow Mapping Table
    op.create_table(
        "flow_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flow_type", sa.Enum(ModelFlowType), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, default=False),
        sa.Column("model_configuration_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"], ["model_configuration.id"], ondelete="CASCADE"
        ),
    )

    # Partial unique index so that there is at most one default for each flow type
    op.create_index(
        "uq_flow_mapping_one_default_per_flow_type",
        "flow_mapping",
        ["flow_type"],
        unique=True,
        postgresql_where=sa.text("is_default is TRUE"),
    )

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

    # Drop default_model_name and is_default_provider from llm provider
    op.drop_column("llm_provider", "default_model_name")
    op.drop_column("llm_provider", "is_default_provider")

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

    # Drop is_default_vision_provider and default_vision_model from llm provider
    op.drop_column("llm_provider", "is_default_vision_provider")
    op.drop_column("llm_provider", "default_vision_model")


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

    # Restore text/default columns
    op.add_column(
        "llm_provider",
        sa.Column("is_default_provider", sa.Boolean(), nullable=True, unique=True),
    )
    op.add_column(
        "llm_provider",
        sa.Column("default_model_name", sa.String(), nullable=True),
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

    # Drop the flow_mapping table (index is dropped automatically with table)
    op.drop_table("flow_mapping")

    # Drop the enum type if it was created by this migration
    # (only if no other tables reference it)
    op.execute("DROP TYPE IF EXISTS modelflowtype;")
