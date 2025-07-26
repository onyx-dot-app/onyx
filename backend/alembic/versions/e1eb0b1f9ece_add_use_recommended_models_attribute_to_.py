"""add use recommended models attribute to LLMProvider

Revision ID: e1eb0b1f9ece
Revises: 62b99efedb8c
Create Date: 2025-07-15 17:29:30.183582

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1eb0b1f9ece"
down_revision = "62b99efedb8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add use_recommended_models column to llm_provider table
    op.add_column(
        "llm_provider",
        sa.Column(
            "use_recommended_models",
            sa.Boolean(),
            nullable=False,
            default=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # Remove use_recommended_models column from llm_provider table
    op.drop_column("llm_provider", "use_recommended_models")
