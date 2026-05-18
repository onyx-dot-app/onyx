"""Add forced_args to tool

Revision ID: 1f4163774e3d
Revises: d129f37b3d87
Create Date: 2026-04-21 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1f4163774e3d"
down_revision = "d129f37b3d87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column("forced_args", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool", "forced_args")
