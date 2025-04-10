"""Add tables for UI-based LLM configuration

Revision ID: 401c1ac29467
Revises: 703313b75876
Create Date: 2024-04-13 18:07:29.153817

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "401c1ac29467"
down_revision = "703313b75876"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=True),
        sa.Column("api_base", sa.String(), nullable=True),
        sa.Column("api_version", sa.String(), nullable=True),
        sa.Column(
            "custom_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("default_model_name", sa.String(), nullable=False),
        sa.Column("fast_default_model_name", sa.String(), nullable=True),
        sa.Column("is_default_provider", sa.Boolean(), unique=True, nullable=True),
        sa.Column("model_names", postgresql.ARRAY(sa.String()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.add_column(
        "persona",
        sa.Column("llm_model_provider_override", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona", "llm_model_provider_override")

    op.drop_table("llm_provider")
