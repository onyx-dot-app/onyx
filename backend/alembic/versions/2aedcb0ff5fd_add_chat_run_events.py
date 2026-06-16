"""add chat run events

Revision ID: 2aedcb0ff5fd
Revises: 01c63968ff8f
Create Date: 2026-06-16 15:02:01.336704

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2aedcb0ff5fd"
down_revision = "01c63968ff8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("model_provider", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_chat_run_chat_session_status",
        "chat_run",
        ["chat_session_id", "status"],
    )
    op.create_index(
        "ix_chat_run_assistant_message",
        "chat_run",
        ["assistant_message_id"],
    )

    op.create_table(
        "chat_run_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("packet_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "seq", name="uq_chat_run_event_run_seq"),
    )
    op.create_index(
        "ix_chat_run_event_run_seq",
        "chat_run_event",
        ["run_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_run_event_run_seq", table_name="chat_run_event")
    op.drop_table("chat_run_event")
    op.drop_index("ix_chat_run_assistant_message", table_name="chat_run")
    op.drop_index("ix_chat_run_chat_session_status", table_name="chat_run")
    op.drop_table("chat_run")
