"""add trace_id to chat message

Revision ID: 087e708d6e26
Revises: 8b5ce697290e
Create Date: 2026-01-20 10:37:13.299608

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "087e708d6e26"
down_revision = "8b5ce697290e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("trace_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "trace_id")
