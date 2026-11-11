"""Key cost overrides on model configuration.

`model_cost_override` was keyed on a provider-type string and a model-name
string. Each override now points at one `model_configuration` row instead, so
two providers of the same type can carry different rates, an override goes
away with its model, and the admin UI can show the model's display name.

Existing rows are copied to every configuration they priced: a configuration
whose name equals the row's model and whose provider type equals the row's
provider ("" matched any provider). Where a configuration matched both a
provider-specific row and a "" row, the provider-specific row wins, as it did
at lookup. Rows that match no configuration priced nothing reachable from the
admin UI and are dropped.

Revision ID: d7f46adc4d49
Revises: b209881eaf72
Create Date: 2026-10-20 14:48:29.360450

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d7f46adc4d49"
down_revision = "b209881eaf72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_cost_override",
        sa.Column("model_configuration_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_model_cost_override_model_configuration_id",
        "model_cost_override",
        "model_configuration",
        ["model_configuration_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The copies below share model/provider with their source row.
    op.drop_constraint(
        "uq_model_cost_override_provider_model", "model_cost_override", type_="unique"
    )

    # One copy per configuration the row priced. Copies of existing rows, so
    # a fresh schema (no overrides) inserts nothing.
    op.execute(
        """
        INSERT INTO model_cost_override (
            model,
            provider,
            input_cost_per_mtok,
            output_cost_per_mtok,
            cache_read_cost_per_mtok,
            created_at,
            updated_at,
            model_configuration_id
        )
        SELECT DISTINCT ON (mc.id)
            o.model,
            o.provider,
            o.input_cost_per_mtok,
            o.output_cost_per_mtok,
            o.cache_read_cost_per_mtok,
            o.created_at,
            o.updated_at,
            mc.id
        FROM model_cost_override o
        JOIN model_configuration mc ON mc.name = o.model
        JOIN llm_provider p ON p.id = mc.llm_provider_id
        WHERE o.model_configuration_id IS NULL
            AND (o.provider = '' OR o.provider = p.provider)
        ORDER BY mc.id, (o.provider = '') ASC, o.id
        """
    )
    # The source rows, and rows that matched no configuration.
    op.execute("DELETE FROM model_cost_override WHERE model_configuration_id IS NULL")

    op.alter_column("model_cost_override", "model_configuration_id", nullable=False)
    op.create_unique_constraint(
        "uq_model_cost_override_model_configuration_id",
        "model_cost_override",
        ["model_configuration_id"],
    )
    op.drop_column("model_cost_override", "model")
    op.drop_column("model_cost_override", "provider")


def downgrade() -> None:
    op.add_column("model_cost_override", sa.Column("model", sa.String(), nullable=True))
    op.add_column(
        "model_cost_override",
        sa.Column("provider", sa.String(), nullable=True, server_default=""),
    )
    op.execute(
        """
        UPDATE model_cost_override o
        SET model = mc.name, provider = p.provider
        FROM model_configuration mc
        JOIN llm_provider p ON p.id = mc.llm_provider_id
        WHERE mc.id = o.model_configuration_id
        """
    )
    # Two providers of one type can now hold rates for the same model name;
    # the old key allows one, so keep the oldest row.
    op.execute(
        """
        DELETE FROM model_cost_override o
        USING model_cost_override keep
        WHERE keep.provider = o.provider
            AND keep.model = o.model
            AND keep.id < o.id
        """
    )
    op.alter_column("model_cost_override", "model", nullable=False)
    op.alter_column("model_cost_override", "provider", nullable=False)

    op.drop_constraint(
        "uq_model_cost_override_model_configuration_id",
        "model_cost_override",
        type_="unique",
    )
    op.drop_constraint(
        "fk_model_cost_override_model_configuration_id",
        "model_cost_override",
        type_="foreignkey",
    )
    op.drop_column("model_cost_override", "model_configuration_id")
    op.create_unique_constraint(
        "uq_model_cost_override_provider_model",
        "model_cost_override",
        ["provider", "model"],
    )
