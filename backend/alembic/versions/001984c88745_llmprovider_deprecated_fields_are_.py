"""LLMProvider deprecated fields are nullable

Revision ID: 001984c88745
Revises: 01f8e6d95a33
Create Date: 2026-02-01 22:24:34.171100

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "001984c88745"
down_revision = "01f8e6d95a33"
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

    # Remove server_default from is_default_vision_provider (was server_default=false())
    op.alter_column(
        "llm_provider",
        "is_default_vision_provider",
        existing_type=sa.Boolean(),
        server_default=None,
    )

    # is_default_provider and default_vision_model are already nullable with no server_default


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

    # Restore server_default for is_default_vision_provider
    op.alter_column(
        "llm_provider",
        "is_default_vision_provider",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
    )
