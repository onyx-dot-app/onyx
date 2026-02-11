"""add processing_duration_seconds to chat_message

Revision ID: 9d1543a37106
Revises: cbc03e08d0f3
Create Date: 2026-01-21 11:42:18.546188

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9d1543a37106"
down_revision = "cbc03e08d0f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("processing_duration_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "processing_duration_seconds")
