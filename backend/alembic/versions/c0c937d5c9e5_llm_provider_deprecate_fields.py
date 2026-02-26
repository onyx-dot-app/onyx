"""llm provider deprecate fields

Revision ID: c0c937d5c9e5
Revises: 8ffcc2bcfc11
Create Date: 2026-02-25 17:35:46.125102

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c0c937d5c9e5"
down_revision = "8ffcc2bcfc11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make default_model_name nullable (was NOT NULL)
    op.alter_column(
        "llm_provider",
        "default_model_name",
        existing_type=sa.String(),
        nullable=True,
    )

    # Drop unique constraint on is_default_provider (defaults now tracked via LLMModelFlow)
    op.drop_constraint(
        "llm_provider_is_default_provider_key",
        "llm_provider",
        type_="unique",
    )

    # Remove server_default from is_default_vision_provider (was server_default=false())
    op.alter_column(
        "llm_provider",
        "is_default_vision_provider",
        existing_type=sa.Boolean(),
        server_default=None,
    )


def downgrade() -> None:
    # Restore default_model_name to NOT NULL (set empty string for any NULLs first)
    op.execute(
        "UPDATE llm_provider SET default_model_name = '' WHERE default_model_name IS NULL"
    )
    op.alter_column(
        "llm_provider",
        "default_model_name",
        existing_type=sa.String(),
        nullable=False,
    )

    # Restore unique constraint on is_default_provider
    op.create_unique_constraint(
        "llm_provider_is_default_provider_key",
        "llm_provider",
        ["is_default_provider"],
    )

    # Restore server_default for is_default_vision_provider
    op.alter_column(
        "llm_provider",
        "is_default_vision_provider",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
    )
