"""Fix invalid model-configurations state

Revision ID: 47a07e1a38f1
Revises: 7a70b7664e37
Create Date: 2025-04-23 15:39:43.159504

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.llm.llm_provider_options import (
    ANTHROPIC_PROVIDER_NAME,
    ANTHROPIC_VISIBLE_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME,
    OPEN_AI_VISIBLE_MODEL_NAMES,
    OPENAI_PROVIDER_NAME,
    VERTEXAI_DEFAULT_FAST_MODEL,
    VERTEXAI_DEFAULT_MODEL,
    VERTEXAI_PROVIDER_NAME,
    fetch_model_names_for_provider_as_set,
)


# revision identifiers, used by Alembic.
revision = "47a07e1a38f1"
down_revision = "7a70b7664e37"
branch_labels = None
depends_on = None


_PROVIDER_TO_VISIBLE_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: set(OPEN_AI_VISIBLE_MODEL_NAMES),
    BEDROCK_PROVIDER_NAME: set(),  # TODO!
    ANTHROPIC_PROVIDER_NAME: set(ANTHROPIC_VISIBLE_MODEL_NAMES),
    VERTEXAI_PROVIDER_NAME: set([VERTEXAI_DEFAULT_MODEL, VERTEXAI_DEFAULT_FAST_MODEL]),
}


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

        models = fetch_model_names_for_provider_as_set(provider_name)

        # if `fetch_model_names_for_provider_as_set` returns `None`, then
        # that means that `provider_name` is not a well-known llm provider.
        if not models:
            continue

        model_configurations = list(
            connection.execute(
                sa.select(
                    model_configuration_table.c.id,
                    model_configuration_table.c.llm_provider_id,
                    model_configuration_table.c.name,
                    model_configuration_table.c.is_visible,
                    model_configuration_table.c.max_input_tokens,
                ).where(model_configuration_table.c.llm_provider_id == llm_provider_id)
            ).fetchall()
        )

        display_model_names: set[str] = _PROVIDER_TO_VISIBLE_MODELS_MAP[provider_name]

        if model_configurations:
            at_least_one_is_public = any(
                [model_configuration[3] for model_configuration in model_configurations]
            )

            # If there is at least one model which is public, this is a valid state.
            # Therefore, don't touch it and move on to the next one.
            if at_least_one_is_public:
                continue

            existing_visible_model_names: set[str] = set(
                [
                    model_configuration[2]
                    for model_configuration in model_configurations
                    if model_configuration[3]
                ]
            )

            for model_name in display_model_names.difference(
                existing_visible_model_names
            ):
                if not model_name:
                    continue

                connection.execute(
                    model_configuration_table.insert().values(
                        llm_provider_id=llm_provider_id,
                        name=model_name,
                        is_visible=True,
                        max_input_tokens=None,
                    )
                )
        else:
            for model_name in models:
                connection.execute(
                    model_configuration_table.insert().values(
                        llm_provider_id=llm_provider_id,
                        name=model_name,
                        is_visible=model_name in display_model_names,
                        max_input_tokens=None,
                    )
                )


def downgrade() -> None:
    pass
