"""
Add GIN index for full-text search on chat_message.message
"""
from alembic import op


# revision identifiers, used by Alembic
revision = "add_message_search_index"
down_revision = None  # Set this to the previous migration ID in your system
branch_labels = None
depends_on = None


def upgrade():
    # Create a GIN index on the to_tsvector of the message column
    op.execute(
        """
        CREATE INDEX idx_chat_message_message_search
        ON chat_message
        USING GIN (to_tsvector('english', message));
        """
    )


def downgrade():
    # Drop the index if we need to roll back
    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_search;")
