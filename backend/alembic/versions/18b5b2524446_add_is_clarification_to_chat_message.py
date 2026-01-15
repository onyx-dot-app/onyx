"""add is_clarification to chat_message

Revision ID: 18b5b2524446
Revises: 87c52ec39f84
Create Date: 2025-01-16

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "18b5b2524446"
down_revision = "87c52ec39f84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column(
            "is_clarification", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "is_clarification")
