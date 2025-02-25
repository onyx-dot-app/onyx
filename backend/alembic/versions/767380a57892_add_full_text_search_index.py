"""Add full text search index

Revision ID: 767380a57892
Revises:
Create Date: 2023-11-15 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "767380a57892"
down_revision = None  # Set this to the previous migration ID in your system
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create a GIN index on the to_tsvector of the message column
    op.execute(
        """
        CREATE INDEX idx_chat_message_message_search
        ON chat_message
        USING GIN (to_tsvector('english', message));
        """
    )


def downgrade() -> None:
    # Drop the index if we need to roll back
    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_search;")
