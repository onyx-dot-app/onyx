"""add marketplace retirement proposal

Revision ID: 0194658d026d
Revises: f5811a494212
Create Date: 2026-11-08 00:57:01.000591

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0194658d026d"
down_revision = "f5811a494212"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace",
        sa.Column("retirement_proposal", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace", "retirement_proposal")
