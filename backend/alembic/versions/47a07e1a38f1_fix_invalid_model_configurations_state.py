"""Fix invalid model-configurations state

Revision ID: 47a07e1a38f1
Revises: 7a70b7664e37
Create Date: 2025-04-23 15:39:43.159504

"""

from alembic import op
from pydantic import BaseModel, ConfigDict
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.llm.llm_provider_options import (
    fetch_model_names_for_provider_as_set,
    fetch_visible_model_names_for_provider_as_set,
)


# revision identifiers, used by Alembic.
revision = "47a07e1a38f1"
down_revision = "7a70b7664e37"
branch_labels = None
depends_on = None


class _SimpleModelConfiguration(BaseModel):
    # Configure model to read from attributes
    model_config = ConfigDict(from_attributes=True)

    id: int
    llm_provider_id: int
    name: str
    is_visible: bool
    max_input_tokens: int | None


def upgrade() -> None:
    llm_provider_table = sa.sql.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.String),
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

        default_models = fetch_model_names_for_provider_as_set(provider_name)
        display_models = fetch_visible_model_names_for_provider_as_set(
            provider_name=provider_name
        )

        # if `fetch_model_names_for_provider_as_set` returns `None`, then
        # that means that `provider_name` is not a well-known llm provider.
        if not default_models:
            continue

        if not display_models:
            raise RuntimeError(
                "If `default_models` is non-None, `display_models` must be non-None too."
            )

        model_configurations = [
            _SimpleModelConfiguration.model_validate(model_configuration)
            for model_configuration in connection.execute(
                sa.select(
                    model_configuration_table.c.id,
                    model_configuration_table.c.llm_provider_id,
                    model_configuration_table.c.name,
                    model_configuration_table.c.is_visible,
                    model_configuration_table.c.max_input_tokens,
                ).where(model_configuration_table.c.llm_provider_id == llm_provider_id)
            ).fetchall()
        ]

        if model_configurations:
            at_least_one_is_visible = any(
                [
                    model_configuration.is_visible
                    for model_configuration in model_configurations
                ]
            )

            # If there is at least one model which is public, this is a valid state.
            # Therefore, don't touch it and move on to the next one.
            if at_least_one_is_visible:
                continue

            existing_visible_model_names: set[str] = set(
                [
                    model_configuration.name
                    for model_configuration in model_configurations
                    if model_configuration.is_visible
                ]
            )

            difference = display_models.difference(existing_visible_model_names)

            for model_name in difference:
                if not model_name:
                    continue

                insert_statement = postgresql.insert(model_configuration_table).values(
                    llm_provider_id=llm_provider_id,
                    name=model_name,
                    is_visible=True,
                    max_input_tokens=None,
                )

                connection.execute(
                    insert_statement.on_conflict_do_update(
                        index_elements=["llm_provider_id", "name"],
                        set_={"is_visible": insert_statement.excluded.is_visible},
                    )
                )
        else:
            for model_name in default_models:
                connection.execute(
                    model_configuration_table.insert().values(
                        llm_provider_id=llm_provider_id,
                        name=model_name,
                        is_visible=model_name in display_models,
                        max_input_tokens=None,
                    )
                )


def downgrade() -> None:
    pass
