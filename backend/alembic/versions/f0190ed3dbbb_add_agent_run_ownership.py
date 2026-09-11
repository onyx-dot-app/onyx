"""add agent run ownership

Revision ID: f0190ed3dbbb
Revises: 287021f3b46c
Create Date: 2026-09-11 14:22:29.035251

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0190ed3dbbb"
down_revision = "287021f3b46c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "chat_session_id",
            sa.UUID(),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("model_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_run_status_updated", "agent_run", ["status", "updated_at"]
    )
    op.create_index(
        "ix_agent_run_session_group", "agent_run", ["chat_session_id", "group_id"]
    )


def downgrade() -> None:
    op.drop_table("agent_run")
