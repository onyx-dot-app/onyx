"""add_indexing_coordination

Revision ID: 2f95e36923e6
Revises: 0816326d83aa
Create Date: 2025-07-10 16:17:57.762182

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f95e36923e6"
down_revision = "0816326d83aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add database-based coordination fields (replacing Redis fencing)
    op.add_column(
        "index_attempt", sa.Column("celery_task_id", sa.String(), nullable=True)
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "cancellation_requested",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # Add batch coordination fields (replacing FileStore state)
    op.add_column(
        "index_attempt", sa.Column("total_batches", sa.Integer(), nullable=True)
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "completed_batches", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "total_failures_batch_level",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
    )

    # Progress tracking for stall detection
    op.add_column(
        "index_attempt",
        sa.Column("last_progress_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "last_batches_completed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Heartbeat tracking for worker liveness detection
    op.add_column(
        "index_attempt",
        sa.Column(
            "heartbeat_counter", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "last_heartbeat_value", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column("last_heartbeat_time", sa.DateTime(timezone=True), nullable=True),
    )

    # Add index for coordination queries
    op.create_index(
        "ix_index_attempt_active_coordination",
        "index_attempt",
        ["connector_credential_pair_id", "search_settings_id", "status"],
    )


def downgrade() -> None:
    # Remove the new index
    op.drop_index("ix_index_attempt_active_coordination", table_name="index_attempt")

    # Remove the new columns
    op.drop_column("index_attempt", "last_batches_completed_count")
    op.drop_column("index_attempt", "last_progress_time")
    op.drop_column("index_attempt", "last_heartbeat_time")
    op.drop_column("index_attempt", "last_heartbeat_value")
    op.drop_column("index_attempt", "heartbeat_counter")
    op.drop_column("index_attempt", "total_chunks")
    op.drop_column("index_attempt", "total_failures_batch_level")
    op.drop_column("index_attempt", "completed_batches")
    op.drop_column("index_attempt", "total_batches")
    op.drop_column("index_attempt", "cancellation_requested")
    op.drop_column("index_attempt", "celery_task_id")
