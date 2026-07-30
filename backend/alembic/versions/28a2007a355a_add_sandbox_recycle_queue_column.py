"""add sandbox recycle queue column

Revision ID: 28a2007a355a
Revises: b3f1c9a27d84
Create Date: 2026-07-30 15:13:36.568577

Queue of live sandboxes waiting to be recycled onto a newer sandbox image.
Nullable with no backfill: existing sandboxes are not retroactively queued, so
the first enqueue after a new image lands is what starts a drain.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "28a2007a355a"
down_revision = "b3f1c9a27d84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox",
        sa.Column("recycle_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Scan predicate for the drain: queued sandboxes, oldest request first. The
    # partial index keeps it off every sandbox that is not waiting for anything,
    # which is nearly all of them nearly all of the time.
    op.create_index(
        "ix_sandbox_recycle_requested",
        "sandbox",
        ["recycle_requested_at"],
        unique=False,
        postgresql_where=sa.text("recycle_requested_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sandbox_recycle_requested", table_name="sandbox")
    op.drop_column("sandbox", "recycle_requested_at")
