"""Add checkpointing/failure handling

Revision ID: b7a7eee5aa15
Revises: f39c5794c10a
Create Date: 2025-01-24 15:17:36.763172

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b7a7eee5aa15"
down_revision = "f39c5794c10a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column("checkpoint_pointer", sa.String(), nullable=True),
    )
    op.add_column(
        "index_attempt",
        sa.Column("poll_range_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "index_attempt",
        sa.Column("poll_range_end", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_index_attempt_cc_pair_settings_poll",
        "index_attempt",
        [
            "connector_credential_pair_id",
            "search_settings_id",
            "status",
            sa.text("time_updated DESC"),
        ],
    )

    # Drop the old IndexAttemptError table
    op.drop_index("index_attempt_id", table_name="index_attempt_errors")
    op.drop_table("index_attempt_errors")

    # Create the new version of the table
    op.create_table(
        "index_attempt_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("index_attempt_id", sa.Integer(), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("document_link", sa.String(), nullable=True),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("failed_time_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_time_range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["index_attempt_id"],
            ["index_attempt.id"],
        ),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
        ),
    )


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")

    # try a few times to drop the table, this has been observed to fail due to other locks
    # blocking the drop
    NUM_TRIES = 10
    for i in range(NUM_TRIES):
        try:
            op.drop_table("index_attempt_errors")
            break
        except Exception as e:
            if i == NUM_TRIES - 1:
                raise e
            print(f"Error dropping table: {e}. Retrying...")

    op.execute("SET lock_timeout = DEFAULT")

    # Recreate the old IndexAttemptError table
    op.create_table(
        "index_attempt_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("index_attempt_id", sa.Integer(), nullable=True),
        sa.Column("batch", sa.Integer(), nullable=True),
        sa.Column("doc_summaries", postgresql.JSONB(), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["index_attempt_id"],
            ["index_attempt.id"],
        ),
    )

    op.create_index(
        "index_attempt_id",
        "index_attempt_errors",
        ["time_created"],
    )

    op.drop_index("ix_index_attempt_cc_pair_settings_poll")
    op.drop_column("index_attempt", "checkpoint_pointer")
    op.drop_column("index_attempt", "poll_range_start")
    op.drop_column("index_attempt", "poll_range_end")
