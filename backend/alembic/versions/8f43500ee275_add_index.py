"""add index

Revision ID: 8f43500ee275
Revises: f13db29f3101
Create Date: 2025-02-24 17:35:33.072714

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "8f43500ee275"
down_revision = "f13db29f3101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create a basic index on the lowercase message column for direct text matching
    op.execute(
        """
        CREATE INDEX idx_chat_message_message_lower
        ON chat_message (LOWER(message))
        """
    )


def downgrade() -> None:
    # Drop the index
    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_lower;")
