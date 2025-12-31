"""add_extra_reasoning_details_to_chat_message_and_tool_call

Revision ID: 7699d3d60c21
Revises: 7206234e012a
Create Date: 2025-12-30 19:22:02.221988

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "7699d3d60c21"
down_revision = "7206234e012a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("extra_reasoning_details", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tool_call",
        sa.Column("extra_reasoning_details", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_call", "extra_reasoning_details")
    op.drop_column("chat_message", "extra_reasoning_details")
