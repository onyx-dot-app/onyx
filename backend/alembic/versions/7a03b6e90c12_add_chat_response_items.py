"""Store ordered agent response items.

Revision ID: 7a03b6e90c12
Revises: a27d64f7b810
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "a27d64f7b810"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_response_item",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("generation_status", sa.String(), nullable=True),
        sa.Column("is_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message", postgresql.JSONB(), nullable=True),
        sa.Column(
            "tool_call_id",
            sa.Integer(),
            sa.ForeignKey("tool_call.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rendering", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("tool_call_id", name="uq_response_item_tool"),
        sa.CheckConstraint("step_index >= 0", name="ck_response_item_step_index"),
        sa.CheckConstraint(
            "(message IS NOT NULL AND tool_call_id IS NULL AND generation_status IS NOT NULL) OR (message IS NULL AND tool_call_id IS NOT NULL AND generation_status IS NULL AND NOT is_answer)",
            name="ck_response_item_kind",
        ),
    )
    op.create_index(
        "ix_response_item_step",
        "chat_response_item",
        ["chat_message_id", "step_index"],
    )
    op.create_index(
        "uq_response_item_step",
        "chat_response_item",
        ["chat_message_id", "step_index"],
        unique=True,
        postgresql_where=sa.text("message IS NOT NULL"),
    )
    op.create_index(
        "uq_response_item_answer",
        "chat_response_item",
        ["chat_message_id"],
        unique=True,
        postgresql_where=sa.text("is_answer"),
    )


def downgrade() -> None:
    op.drop_table("chat_response_item")
