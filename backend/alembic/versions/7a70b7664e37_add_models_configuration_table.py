"""Add models-configuration table

Revision ID: 7a70b7664e37
Revises: cf90764725d8
Create Date: 2025-04-10 15:00:35.984669

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7a70b7664e37"
down_revision = "d961aca62eb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llm_provider_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["llm_provider_id"], ["llm_provider.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("llm_provider_id", "name"),
    )

    # Create temporary sqlalchemy references to tables for data migration
    llm_provider_table = sa.sql.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("model_names", postgresql.ARRAY(sa.String)),
        sa.column("display_model_names", postgresql.ARRAY(sa.String)),
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
            llm_provider_table.c.model_names,
            llm_provider_table.c.display_model_names,
        )
    ).fetchall()

    for llm_provider in llm_providers:
        provider_id = llm_provider[0]
        model_names = llm_provider[1] or []
        display_model_names = llm_provider[2] or []

        # Create a set of display models for quick lookup
        display_set = set(display_model_names)

        # Insert all models from model_names
        for model_name in model_names:
            # If model is in display_model_names, set is_visible to True
            is_visible = model_name in display_set

            connection.execute(
                model_configuration_table.insert().values(
                    llm_provider_id=provider_id,
                    name=model_name,
                    is_visible=is_visible,
                    max_input_tokens=None,
                )
            )

    op.drop_column("llm_provider", "model_names")
    op.drop_column("llm_provider", "display_model_names")


def downgrade() -> None:
    llm_provider = sa.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("model_names", postgresql.ARRAY(sa.String)),
        sa.column("display_model_names", postgresql.ARRAY(sa.String)),
    )

    model_configuration = sa.table(
        "model_configuration",
        sa.column("id", sa.Integer),
        sa.column("llm_provider_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_visible", sa.Boolean),
        sa.column("max_input_tokens", sa.Integer),
    )
    op.add_column(
        "llm_provider",
        sa.Column(
            "model_names",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "llm_provider",
        sa.Column(
            "display_model_names",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
    )

    connection = op.get_bind()
    provider_ids = connection.execute(sa.select(llm_provider.c.id)).fetchall()

    for (provider_id,) in provider_ids:
        # Get all models for this provider
        models = connection.execute(
            sa.select(
                model_configuration.c.name, model_configuration.c.is_visible
            ).where(model_configuration.c.llm_provider_id == provider_id)
        ).fetchall()

        all_models = [model[0] for model in models]
        visible_models = [model[0] for model in models if model[1]]

        # Update provider with arrays
        op.execute(
            llm_provider.update()
            .where(llm_provider.c.id == provider_id)
            .values(model_names=all_models, display_model_names=visible_models)
        )

    op.drop_table("model_configuration")
