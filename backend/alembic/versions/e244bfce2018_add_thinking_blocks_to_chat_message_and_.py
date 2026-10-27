"""add thinking_blocks to chat_message and tool_call

Revision ID: e244bfce2018
Revises: ca7cc9a98a6b
Create Date: 2026-10-27 19:52:22.484950

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e244bfce2018"
down_revision = "ca7cc9a98a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("thinking_blocks", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tool_call",
        sa.Column("thinking_blocks", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_call", "thinking_blocks")
    op.drop_column("chat_message", "thinking_blocks")
