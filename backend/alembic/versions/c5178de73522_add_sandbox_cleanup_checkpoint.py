"""add sandbox cleanup checkpoint

Revision ID: c5178de73522
Revises: 9071f636d5f2
Create Date: 2026-10-22 11:30:55.590959

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c5178de73522"
down_revision = "9071f636d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox", sa.Column("cleanup_checkpoint", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sandbox", "cleanup_checkpoint")
