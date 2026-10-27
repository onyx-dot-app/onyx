"""Record when an index attempt finished.

Revision ID: d29117d86fdd
Revises: a27d64f7b810
"""

from alembic import op
import sqlalchemy as sa

revision = "d29117d86fdd"
down_revision = "a27d64f7b810"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column("time_finished", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "time_finished")
