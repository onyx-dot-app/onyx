"""record the documents a prune could not remove

Revision ID: c7e1a2f4b9d3
Revises: c3d9a1f4b7e2
Create Date: 2026-10-16 20:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7e1a2f4b9d3"
down_revision = "c3d9a1f4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_record",
        sa.Column("num_docs_failed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("sync_record", "num_docs_failed")
