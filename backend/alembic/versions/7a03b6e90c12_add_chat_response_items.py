"""Store ordered model generations.

Revision ID: 7a03b6e90c12
Revises: e7a3c1f5b2d4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "e7a3c1f5b2d4"
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
        sa.Column("generation_status", sa.String(), nullable=False),
        sa.Column("is_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message", postgresql.JSONB(), nullable=False),
        sa.Column("rendering", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("step_index >= 0", name="ck_response_item_step_index"),
    )
    op.create_index(
        "uq_response_item_step",
        "chat_response_item",
        ["chat_message_id", "step_index"],
        unique=True,
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
