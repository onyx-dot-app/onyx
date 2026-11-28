"""Keep a history of connector check runs, let prunes record why they failed,
schedule check runs, and let an admin release the indexing hold.

Revision ID: e7a3c1f5b2d4
Revises: d29117d86fdd
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7a3c1f5b2d4"
down_revision = "d29117d86fdd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_check_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("time_finished", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["connector.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_capability_check_run_scope_time",
        "capability_check_run",
        ["credential_id", "connector_id", "time_created"],
    )
    # Serves the cascade when a connector is deleted.
    op.create_index(
        "ix_capability_check_run_connector_id",
        "capability_check_run",
        ["connector_id"],
    )
    op.add_column("sync_record", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("connector", sa.Column("check_freq", sa.Integer(), nullable=True))
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "indexing_hold_released_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "indexing_hold_released_at")
    op.drop_column("connector", "check_freq")
    op.drop_column("sync_record", "error_message")
    op.drop_index(
        "ix_capability_check_run_connector_id", table_name="capability_check_run"
    )
    op.drop_index(
        "ix_capability_check_run_scope_time", table_name="capability_check_run"
    )
    op.drop_table("capability_check_run")
