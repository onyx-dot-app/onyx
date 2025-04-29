"""Add model-configuration table

Revision ID: 7a70b7664e37
Revises: d961aca62eb3
Create Date: 2025-04-10 15:00:35.984669

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.llm.llm_provider_options import (
    fetch_model_names_for_provider_as_set,
    fetch_visible_model_names_for_provider_as_set,
)

# revision identifiers, used by Alembic.
revision = "7a70b7664e37"
down_revision = "d961aca62eb3"
branch_labels = None
depends_on = None


def _resolve(
    provider_name: str,
    model_names: list[str] | None,
    display_model_names: list[str] | None,
    default_model_name: str,
    fast_default_model_name: str | None,
) -> set[tuple[str, bool]]:
    models = set(model_names) if model_names else None
    display_models = set(display_model_names) if display_model_names else None

    # If both are defined, we need to make sure that `model_names` is a superset of `display_model_names`.
    if models and display_models:
        models = display_models.union(models)

    # If only `model_names` is defined, then:
    #   - If default-model-names are available for the `provider_name`, then set `display_model_names` to it
    #     and set `model_names` to the union of those default-model-names with itself.
    #   - If no default-model-names are available, then set `display_models` to `models`.
    #
    # This preserves the invariant that `display_models` is a subset of `models`.
    elif models and not display_models:
        visible_default_models = fetch_visible_model_names_for_provider_as_set(
            provider_name=provider_name
        )
        if visible_default_models:
            display_models = set(visible_default_models)
            models = display_models.union(models)
        else:
            display_models = set(models)

    # If only the `display_model_names` are defined, then set `models` to the union of `display_model_names`
    # and the default-model-names for that provider.
    #
    # This will also preserve the invariant that `display_models` is a subset of `models`.
    elif not models and display_models:
        default_models = fetch_model_names_for_provider_as_set(
            provider_name=provider_name
        )
        if default_models:
            models = display_models.union(default_models)
        else:
            models = set(display_models)

    # If neither are defined, then set `models` and `display_models` to the default-model-names for the given provider.
    #
    # This will also preserve the invariant that `display_models` is a subset of `models`.
    else:
        default_models = fetch_model_names_for_provider_as_set(
            provider_name=provider_name
        )
        visible_default_models = fetch_visible_model_names_for_provider_as_set(
            provider_name=provider_name
        )

        if default_models:
            if not visible_default_models:
                raise RuntimeError
                raise RuntimeError(
                    "If `default_models` is non-None, `visible_default_models` must be non-None too."
                )
            models = default_models
            display_models = visible_default_models

        # This is not a well-known llm-provider; we can't provide any model suggestions.
        # Therefore, we set to the empty set and continue
        else:
            models = set()
            display_models = set()

    # It is possible that `default_model_name` is not in `models` and is not in `display_models`.
    # It is also possible that `fast_default_model_name` is not in `models` and is not in `display_models`.
    models.add(default_model_name)
    if fast_default_model_name:
        models.add(fast_default_model_name)
    display_models.add(default_model_name)
    if fast_default_model_name:
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
            llm_provider_table.c.provider,
            llm_provider_table.c.model_names,
            llm_provider_table.c.display_model_names,
            llm_provider_table.c.default_model_name,
            llm_provider_table.c.fast_default_model_name,
        )
    ).fetchall()

    for llm_provider in llm_providers:
        provider_id = llm_provider[0]
        provider_name = llm_provider[1]
        model_names = llm_provider[2]
        display_model_names = llm_provider[3]
        default_model_name = llm_provider[4]
        fast_default_model_name = llm_provider[5]

        model_configurations = _resolve(
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
