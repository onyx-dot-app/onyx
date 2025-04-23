"""Add model-configuration table

Revision ID: 7a70b7664e37
Revises: d961aca62eb3
Create Date: 2025-04-10 15:00:35.984669

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.llm.llm_provider_options import PROVIDER_TO_MODELS_MAP

# revision identifiers, used by Alembic.
revision = "7a70b7664e37"
down_revision = "d961aca62eb3"
branch_labels = None
depends_on = None


def get(provider_name: str) -> set[str] | None:
    model_names: list[str] | None = PROVIDER_TO_MODELS_MAP.get(provider_name)
    return set(model_names) if model_names else None


def resolve(
    provider_name: str,
    model_names: list[str] | None,
    display_model_names: list[str] | None,
    default_model_name: str,
    fast_default_model_name: str,
) -> set[tuple[str, bool]]:
    models = set(model_names) if model_names else None
    display_models = set(display_model_names) if display_model_names else None

    # if both are defined, we need to make sure that `model_names` is a superset of `display_model_names`
    if models and display_models:
        if not display_models.issubset(models):
            models = display_models.union(models)

    # if only the model-names are defined,
    elif models and not display_models:
        new = get(provider_name)
        display_models = models.union(new) if new else set(models)

    # if only the display-model-names are defined, then
    elif not models and display_models:
        new = get(provider_name)
        models = display_models.union(new) if new else set(display_models)

    else:
        new = get(provider_name)
        models = set(new) if new else set()
        display_models = set(new) if new else set()

    models.add(default_model_name)
    models.add(fast_default_model_name)
    display_models.add(default_model_name)
    display_models.add(fast_default_model_name)

    return set([(model, model in display_models) for model in models])


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
            llm_provider_table.c.model_names,
            llm_provider_table.c.display_model_names,
        )
    ).fetchall()

    for llm_provider in llm_providers:
        provider_id = llm_provider[0]
        provider_name = llm_provider[1]
        model_names = llm_provider[2]
        display_model_names = llm_provider[3]
        default_model_name = llm_provider[4]
        fast_default_model_name = llm_provider[5]

        model_configurations = resolve(
            provider_name=provider_name,
            model_names=model_names,
            display_model_names=display_model_names,
            default_model_name=default_model_name,
            fast_default_model_name=fast_default_model_name,
        )

        for model_name, is_visible in model_configurations:
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
