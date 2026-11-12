"""Store the tool selection of a chat session.

Revision ID: 43484c519a86
Revises: fdaeeca238a1
Create Date: 2026-11-11 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "43484c519a86"
down_revision = "fdaeeca238a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_session",
        sa.Column("tool_selection", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "tool_selection")
