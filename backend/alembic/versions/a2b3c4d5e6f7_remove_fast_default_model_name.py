"""Remove fast_default_model_name from llm_provider

Revision ID: a2b3c4d5e6f7
Revises: 2a391f840e85
Create Date: 2024-12-17

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "2a391f840e85"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("llm_provider", "fast_default_model_name")


def downgrade() -> None:
    op.add_column(
        "llm_provider",
        sa.Column("fast_default_model_name", sa.String(), nullable=True),
    )
