"""Store agent responses, child conversations, and resumable checkpoints.

Revision ID: 7a03b6e90c12
Revises: ac05f4a21dbd
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_message",
        "message_type",
        existing_type=sa.String(9),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.execute("""
        UPDATE chat_message SET message_type = 'SUMMARY'
        WHERE message_type = 'ASSISTANT' AND last_summarized_message_id IS NOT NULL
    """)
    op.alter_column("tool_call", "tool_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "chat_session", sa.Column("spawned_by_message_id", sa.Integer(), nullable=True)
    )
    op.add_column("chat_session", sa.Column("agent_name", sa.String(), nullable=True))
    op.add_column(
        "chat_session",
        sa.Column("restoration_config", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_session_spawned_by_message",
        "chat_session",
        "chat_message",
        ["spawned_by_message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_chat_session_spawned_by_message_id",
        "chat_session",
        ["spawned_by_message_id"],
    )
    for column in (
        sa.Column("response_status", sa.String(), nullable=True),
        sa.Column("response_failure", postgresql.JSONB(), nullable=True),
        sa.Column("invoking_tool_call_id", sa.Integer(), nullable=True),
        sa.Column("summary_covered_count", sa.Integer(), nullable=True),
        sa.Column("summary_covered_digest", sa.String(), nullable=True),
    ):
        op.add_column("chat_message", column)
    op.create_foreign_key(
        "fk_chat_message_invocation",
        "chat_message",
        "tool_call",
        ["invoking_tool_call_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_chat_message_invoking_tool_call_id",
        "chat_message",
        ["invoking_tool_call_id"],
    )
    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )
    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for column in (
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("argument_error", sa.Text(), nullable=True),
        sa.Column("raw_arguments", sa.Text(), nullable=True),
        sa.Column(
            "arguments_complete", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("operation_status", sa.String(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
    ):
        op.add_column("tool_call", column)
    op.create_table(
        "chat_response_item",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column(
            "tool_call_id",
            sa.Integer(),
            sa.ForeignKey("tool_call.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rendering", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "chat_message_id", "position", name="uq_response_item_position"
        ),
        sa.UniqueConstraint("tool_call_id", "kind", name="uq_response_item_tool_kind"),
        sa.CheckConstraint(
            "position >= 0 AND step_index >= 0", name="ck_response_item_position"
        ),
        sa.CheckConstraint(
            "(kind IN ('generation', 'text', 'reasoning') AND content IS NOT NULL AND tool_call_id IS NULL) OR (kind IN ('tool_call', 'tool_result') AND content IS NULL AND tool_call_id IS NOT NULL)",
            name="ck_response_item_content",
        ),
    )
    op.create_index(
        "ix_chat_response_item_chat_message_id",
        "chat_response_item",
        ["chat_message_id"],
    )

    op.add_column("chat_message", sa.Column("run_id", sa.String(), nullable=True))
    op.create_unique_constraint("uq_chat_message_run_id", "chat_message", ["run_id"])
    op.create_table(
        "chat_response_checkpoint",
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_response_checkpoint")
    op.drop_constraint("uq_chat_message_run_id", "chat_message", type_="unique")
    op.drop_column("chat_message", "run_id")

    # The public answer projections remain readable by the original schema.
    op.execute("""
        UPDATE tool_call SET tool_call_response = CASE jsonb_typeof(result->'content')
            WHEN 'string' THEN result->>'content'
            ELSE coalesce((SELECT string_agg(block->>'text', '' ORDER BY ordinal)
                FROM jsonb_array_elements(result->'content') WITH ORDINALITY AS blocks(block, ordinal)
                WHERE block->>'type' = 'text'), '') END
        WHERE result IS NOT NULL AND result <> 'null'::jsonb
    """)
    op.drop_table("chat_response_item")
    op.execute("DELETE FROM chat_session WHERE spawned_by_message_id IS NOT NULL")
    op.execute("DELETE FROM tool_call WHERE tool_id IS NULL")
    op.alter_column("tool_call", "tool_id", existing_type=sa.Integer(), nullable=False)
    op.execute("DELETE FROM chat_message WHERE summary_covered_count IS NOT NULL")
    op.execute("""
        UPDATE chat_message SET message_type = 'ASSISTANT'
        WHERE message_type = 'SUMMARY'
    """)
    for column in (
        "response_status",
        "response_failure",
        "invoking_tool_call_id",
        "summary_covered_count",
        "summary_covered_digest",
    ):
        op.drop_column("chat_message", column)
    for column in (
        "spawned_by_message_id",
        "agent_name",
        "restoration_config",
    ):
        op.drop_column("chat_session", column)
    for column in (
        "tool_name",
        "argument_error",
        "raw_arguments",
        "arguments_complete",
        "operation_status",
        "result",
    ):
        op.drop_column("tool_call", column)
    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )
    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["id"],
    )
    op.alter_column(
        "chat_message",
        "message_type",
        existing_type=sa.String(32),
        type_=sa.String(9),
        existing_nullable=False,
    )
