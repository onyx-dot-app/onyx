"""Fix invalid model-configurations state

Revision ID: 47a07e1a38f1
Revises: 7a70b7664e37
Create Date: 2025-04-23 15:39:43.159504

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.llm.llm_provider_options import fetch_model_names_for_provider_as_set


# revision identifiers, used by Alembic.
revision = "47a07e1a38f1"
down_revision = "7a70b7664e37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    llm_provider_table = sa.sql.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.Integer),
        sa.column("model_names", postgresql.ARRAY(sa.String)),
        sa.column("display_model_names", postgresql.ARRAY(sa.String)),
        sa.column("default_model_name", sa.String),
        sa.column("fast_default_model_name", sa.String),
    )
    model_configuration_table = sa.sql.table(
        "model_configuration",
        sa.column("id", sa.Integer),
        sa.column("llm_provider_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_visible", sa.Boolean),
        sa.column("max_input_tokens", sa.Integer),
    )

    connection = op.get_bind()

    llm_providers = connection.execute(
        sa.select(
            llm_provider_table.c.id,
            llm_provider_table.c.provider,
        )
    ).fetchall()

    for llm_provider in llm_providers:
        llm_provider_id, provider_name = llm_provider

        models = fetch_model_names_for_provider_as_set(provider_name)

        # if `fetch_model_names_for_provider_as_set` returns `None`, then
        # that means that `provider_name` is not a well-known llm provider.
        if not models:
            continue

        _model_configurations = connection.execute(
            sa.select(
                model_configuration_table.c.id,
                model_configuration_table.c.llm_provider_id,
                model_configuration_table.c.name,
                model_configuration_table.c.is_visible,
            ).where(model_configuration_table.c.llm_provider_id == llm_provider_id)
        ).fetchall()

        all_are_private = True

        # If `not all_are_private`, then there must exist at least one
        # model which is public. Therefore, this is a valid state;
        # don't touch this state and move onto the next one.
        if not all_are_private:
            continue

        ...


def downgrade() -> None:
    pass
