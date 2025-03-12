"""add_default_vision_provider_to_llm_provider

Revision ID: df46c75b714e
Revises: 3934b1bc7b62
Create Date: 2025-03-11 16:20:19.038945

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "df46c75b714e"
down_revision = "3934b1bc7b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_provider",
        sa.Column(
            "is_default_vision_provider", sa.Boolean(), nullable=True, unique=True
        ),
    )
    op.add_column(
        "llm_provider", sa.Column("default_vision_model", sa.String(), nullable=True)
    )
    # Add unique constraint for is_default_vision_provider
    op.create_unique_constraint(
        "uq_llm_provider_is_default_vision_provider",
        "llm_provider",
        ["is_default_vision_provider"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_llm_provider_is_default_vision_provider", "llm_provider", type_="unique"
    )
    op.drop_column("llm_provider", "default_vision_model")
    op.drop_column("llm_provider", "is_default_vision_provider")
