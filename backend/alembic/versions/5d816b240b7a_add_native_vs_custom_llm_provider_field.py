"""Add native-vs-custom LLM Provider field

Revision ID: 5d816b240b7a
Revises: 7a70b7664e37
Create Date: 2025-04-21 14:17:15.812325

"""

from alembic import op
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from backend.onyx.llm.llm_provider_options import (
    fetch_available_well_known_llms,
    fetch_model_names_for_provider_as_set,
)


# revision identifiers, used by Alembic.
revision = "5d816b240b7a"
down_revision = "7a70b7664e37"
branch_labels = None
depends_on = None


NATIVE_VARIANT = "NATIVE"
CUSTOM_VARIANT = "CUSTOM"


class _SimpleLLMProvider(BaseModel):
    # Configure model to read from attributes
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str


def upgrade() -> None:
    llm_provider_table = sa.sql.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column(
            "native_or_custom",
            sa.Enum(NATIVE_VARIANT, CUSTOM_VARIANT, name="source_type"),
        ),
    )
    model_configuration_table = sa.sql.table(
        "model_configuration",
        sa.column("llm_provider_id", sa.Integer),
        sa.column("name", sa.String),
    )

    connection = op.get_bind()
    source_type = sa.Enum(NATIVE_VARIANT, CUSTOM_VARIANT, name="source_type")
    source_type.create(op.get_bind())

    op.add_column(
        "llm_provider",
        sa.Column(
            "native_or_custom",
            sa.Enum(
                NATIVE_VARIANT, CUSTOM_VARIANT, name="source_type", create_type=False
            ),
            autoincrement=False,
            # Set to nullable first.
            # Then, find the appropriate value to put in each row, and update accordingly.
            # Finally, update column to be non-nullable.
            nullable=True,
        ),
    )

    llm_providers = [
        _SimpleLLMProvider(
            id=row[0],
            provider=row[1],
        )
        for row in connection.execute(
            sa.select(
                llm_provider_table.c.id,
                llm_provider_table.c.provider,
                llm_provider_table.c.native_or_custom,
            )
        ).fetchall()
    ]

    well_known_llm_provider_names = set(
        llm_provider.name for llm_provider in fetch_available_well_known_llms()
    )

    for llm_provider in llm_providers:
        if llm_provider.provider not in well_known_llm_provider_names:
            connection.execute(
                sa.update(llm_provider_table).values(native_or_custom=CUSTOM_VARIANT)
            )
            continue

        default_model_names = fetch_model_names_for_provider_as_set(
            provider_name=llm_provider.provider
        )
        if not default_model_names:
            raise RuntimeError("")

        current_model_names = set(
            row[0]
            for row in connection.execute(
                sa.select(
                    model_configuration_table.c.name,
                ).where(model_configuration_table.c.llm_provider_id == llm_provider.id)
            ).fetchall()
        )

        native_or_custom = (
            NATIVE_VARIANT
            if current_model_names.issubset(default_model_names)
            else CUSTOM_VARIANT
        )

        connection.execute(
            sa.update(llm_provider_table).values(native_or_custom=native_or_custom)
        )

    op.alter_column("llm_provider", "native_or_custom", nullable=False)


def downgrade() -> None:
    connection = op.get_bind()
    op.drop_column("llm_provider", "native_or_custom")
    sa.Enum(NATIVE_VARIANT, CUSTOM_VARIANT, name="source_type").drop(connection)
