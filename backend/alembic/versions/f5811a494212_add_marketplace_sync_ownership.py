"""add marketplace sync ownership

Revision ID: f5811a494212
Revises: 99814f2364b2
Create Date: 2026-11-08 00:36:10.578878

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f5811a494212"
down_revision = "99814f2364b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace",
        sa.Column(
            "sync_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("marketplace", sa.Column("sync_owner", sa.UUID(), nullable=True))
    op.add_column(
        "marketplace",
        sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    for name in (
        "sync_lease_expires_at",
        "sync_started_at",
        "sync_dispatch_after",
        "sync_retry_after",
    ):
        op.add_column(
            "marketplace", sa.Column(name, sa.DateTime(timezone=True), nullable=True)
        )
    op.add_column(
        "marketplace", sa.Column("sync_status", sa.String(length=18), nullable=True)
    )


def downgrade() -> None:
    for name in (
        "sync_retry_after",
        "sync_attempts",
        "sync_status",
        "sync_dispatch_after",
        "sync_started_at",
        "sync_lease_expires_at",
        "sync_owner",
        "sync_requested",
    ):
        op.drop_column("marketplace", name)
