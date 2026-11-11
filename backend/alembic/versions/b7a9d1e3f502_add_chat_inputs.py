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
            "ui_preferences",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Keep paste_as_tile available for draining API pods that select it.
    op.execute(
        sa.text(
            'UPDATE "user" SET ui_preferences = \'{"paste_as_tile": true}\'::jsonb '
            "WHERE paste_as_tile IS TRUE"
        )
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "response_inputs_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
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
        sa.Column("max_steps", sa.Integer(), nullable=True),
        sa.Column("total_timeout_s", sa.Float(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "response_item_id",
            sa.String(),
            sa.ForeignKey("chat_response_item.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(response_item_id IS NULL AND position IS NULL) OR (response_item_id IS NOT NULL AND position IS NOT NULL AND position >= 0)",
            name="ck_chat_input_acceptance",
        ),
        sa.CheckConstraint(
            "response_item_id IS NOT NULL OR (delivery IS NOT NULL AND ((source = 'human' AND invoking_tool_call_id IS NULL AND max_steps IS NULL) OR "
            "(source = 'agent' AND invoking_tool_call_id IS NOT NULL AND max_steps IS NOT NULL AND max_steps > 0)))",
            name="ck_chat_input_pending",
        ),
        sa.CheckConstraint(
            "source IN ('human', 'agent', 'agent_result')", name="ck_chat_input_source"
        ),
        sa.CheckConstraint(
            "delivery IS NULL OR delivery IN ('send', 'queue') OR "
            "(delivery = 'interrupt' AND source = 'human')",
            name="ck_chat_input_delivery",
        ),
    )
    op.create_index(
        "uq_chat_input_position",
        "chat_input",
        ["response_item_id", "position"],
        unique=True,
    )
    op.create_index(
        "uq_chat_input_message",
        "chat_input",
        ["response_item_id", "message_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_input_pending",
        "chat_input",
        ["recipient_session_id", "id"],
        postgresql_where=sa.text("response_item_id IS NULL"),
    )

    for column in (
        "recipient_session_id",
        "invoking_tool_call_id",
        "source_response_id",
        "target_response_id",
    ):
        op.create_index(f"ix_chat_input_{column}", "chat_input", [column])


def downgrade() -> None:
    op.execute(
        sa.text(
            'UPDATE "user" SET paste_as_tile = '
            "COALESCE(ui_preferences -> 'paste_as_tile' = 'true'::jsonb, false) "
            "WHERE paste_as_tile IS DISTINCT FROM "
            "COALESCE(ui_preferences -> 'paste_as_tile' = 'true'::jsonb, false)"
        )
    )
    op.drop_column("user", "ui_preferences")
    op.drop_table("chat_input")
    op.drop_column("chat_message", "response_inputs_closed")
