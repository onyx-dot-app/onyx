"""add checkpoint to doc permission sync attempt

Revision ID: 69a7c4a99c09
Revises: 9071f636d5f2
Create Date: 2026-10-22 09:15:00.454473

"""

from alembic import op
import sqlalchemy as sa


revision = "69a7c4a99c09"
down_revision = "9071f636d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doc_permission_sync_attempt",
        sa.Column("checkpoint_pointer", sa.String(), nullable=True),
    )
    op.add_column(
        "doc_permission_sync_attempt",
        sa.Column("poll_range_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "doc_permission_sync_attempt",
        sa.Column("poll_range_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("doc_permission_sync_attempt", "poll_range_end")
    op.drop_column("doc_permission_sync_attempt", "poll_range_start")
    op.drop_column("doc_permission_sync_attempt", "checkpoint_pointer")
