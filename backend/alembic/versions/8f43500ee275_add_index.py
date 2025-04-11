"""add index

Revision ID: 8f43500ee275
Revises: da42808081e3
Create Date: 2025-02-24 17:35:33.072714

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "8f43500ee275"
down_revision = "da42808081e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create a basic index on the lowercase message column for direct text matching
    # Limit to 1500 characters to stay well under the 2856 byte limit of btree version 4
    # op.execute(
    #     """
    #     CREATE INDEX idx_chat_message_message_lower
    #     ON chat_message (LOWER(substring(message, 1, 1500)))
    #     """
    # )
    pass


def downgrade() -> None:
    # Drop the index
    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_lower;")
