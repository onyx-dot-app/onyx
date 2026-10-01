"""add vertex embedding authentication config

Revision ID: 38720c9e7f8f
Revises: 3067343245d1
Create Date: 2026-09-30 16:05:20.845370

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "38720c9e7f8f"
down_revision = "3067343245d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "embedding_provider",
        sa.Column("vertex_config", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("embedding_provider", "vertex_config")
