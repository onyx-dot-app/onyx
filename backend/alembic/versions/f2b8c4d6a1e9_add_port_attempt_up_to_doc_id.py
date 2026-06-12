"""add port_attempt up_to_doc_id

Revision ID: f2b8c4d6a1e9
Revises: e7f3a9b2c1d4
Create Date: 2026-06-11 12:30:00.000000

Additive: the upper doc-id boundary a port snapshots at start so it covers the
backlog as of start, not docs added during the run. Nullable; null = unbounded.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f2b8c4d6a1e9"
down_revision = "e7f3a9b2c1d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "port_attempt",
        sa.Column("up_to_doc_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("port_attempt", "up_to_doc_id")
