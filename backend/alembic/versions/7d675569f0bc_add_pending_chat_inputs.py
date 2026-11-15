"""Store pending chat messages and the interrupt preference.

Revision ID: 7d675569f0bc
Revises: 01300220f1e1
Create Date: 2026-11-11 18:02:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7d675569f0bc"
down_revision = "01300220f1e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "interrupt_on_send",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Set by Stop; a paused queue starts no queued turn until the next turn starts.
    op.add_column(
        "chat_session",
        sa.Column("queue_paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "chat_input",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recipient_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "target_response_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("delivery", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "deep_research", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("llm_override", postgresql.JSONB(), nullable=True),
        # IS TRUE: a NULL comparison makes CHECK pass, so require a true result.
        sa.CheckConstraint(
            "(source = 'human' AND delivery IN ('send', 'queue', 'interrupt')) IS TRUE",
            name="ck_chat_input_source",
        ),
    )
    op.create_index(
        "ix_chat_input_recipient", "chat_input", ["recipient_session_id", "id"]
    )
    op.create_index(
        "ix_chat_input_target_response_id", "chat_input", ["target_response_id"]
    )


def downgrade() -> None:
    op.drop_table("chat_input")
    op.drop_column("chat_session", "queue_paused_at")
    op.drop_column("user", "interrupt_on_send")
