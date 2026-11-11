"""add conversion dispatch reference to index_attempt

`uses_conversion_stage` marks an attempt whose docfetching lists stub
batches. `last_dispatch_task_id` and `last_dispatch_at` name the last task
that sent stub batches to conversion, so the watchdog can tell a broken
chain from a dead attempt.

Revision ID: 5d1f8a6c2e47
Revises: 3b7e2c9d41a6
Create Date: 2026-11-11 02:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5d1f8a6c2e47"
down_revision = "3b7e2c9d41a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column(
            "uses_conversion_stage",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column("last_dispatch_task_id", sa.String(), nullable=True),
    )
    op.add_column(
        "index_attempt",
        sa.Column("last_dispatch_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "last_dispatch_at")
    op.drop_column("index_attempt", "last_dispatch_task_id")
    op.drop_column("index_attempt", "uses_conversion_stage")
