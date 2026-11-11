"""Store pending chat messages and accepted generation inputs.

Revision ID: b7a9d1e3f502
Revises: fdaeeca238a1
Create Date: 2026-11-09 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7a9d1e3f502"
down_revision = "fdaeeca238a1"
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
    op.add_column(
        "chat_response_item",
        sa.Column(
            "inputs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
            "invoking_tool_call_id",
            sa.Integer(),
            sa.ForeignKey("tool_call.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "source_response_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "target_response_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "root_response_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("max_steps", sa.Integer(), nullable=True),
        sa.Column("total_timeout_s", sa.Float(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(source = 'human' AND delivery IN ('send', 'queue', 'interrupt') "
            "AND invoking_tool_call_id IS NULL AND max_steps IS NULL "
            "AND root_response_id IS NULL) OR "
            "(source = 'agent' AND delivery IN ('send', 'queue') "
            "AND invoking_tool_call_id IS NOT NULL AND max_steps > 0 "
            "AND root_response_id IS NOT NULL) OR "
            "(source = 'agent_result' AND delivery IS NULL "
            "AND source_response_id IS NOT NULL AND root_response_id IS NOT NULL)",
            name="ck_chat_input_source",
        ),
    )
    op.create_index(
        "ix_chat_input_recipient", "chat_input", ["recipient_session_id", "id"]
    )
    for column in (
        "invoking_tool_call_id",
        "source_response_id",
        "target_response_id",
        "root_response_id",
    ):
        op.create_index(f"ix_chat_input_{column}", "chat_input", [column])
    # Branch walks and child-history queries join on these parent links.
    op.create_index(
        "ix_chat_message_parent_message_id", "chat_message", ["parent_message_id"]
    )
    op.create_index(
        "ix_tool_call_parent_chat_message_id", "tool_call", ["parent_chat_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_parent_chat_message_id", table_name="tool_call")
    op.drop_index("ix_chat_message_parent_message_id", table_name="chat_message")
    op.drop_table("chat_input")
    op.drop_column("chat_response_item", "inputs")
    op.drop_column("user", "interrupt_on_send")
