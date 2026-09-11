"""Add durable agent stream completion acknowledgement.

Revision ID: 483196be2f23
Revises: f0190ed3dbbb
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa

revision = "483196be2f23"
down_revision = "f0190ed3dbbb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_run",
        sa.Column(
            "stream_closed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index(
        "ix_agent_run_pending_stream",
        "agent_run",
        ["stream_closed", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_pending_stream", table_name="agent_run")
    op.drop_column("agent_run", "stream_closed")
