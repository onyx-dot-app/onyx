"""add snapshot tree_digest

Revision ID: eefb92217285
Revises: 1cb59a95b250
Create Date: 2026-06-11 09:21:40.264488

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "eefb92217285"
down_revision = "1cb59a95b250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshot",
        sa.Column("tree_digest", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snapshot", "tree_digest")
