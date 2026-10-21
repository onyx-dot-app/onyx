"""add sandbox cleanup checkpoint

Revision ID: 45662b7b63a2
Revises: 4d8453213439
Create Date: 2026-10-21 11:49:13.883386

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "45662b7b63a2"
down_revision = "4d8453213439"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox", sa.Column("cleanup_checkpoint", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sandbox", "cleanup_checkpoint")
