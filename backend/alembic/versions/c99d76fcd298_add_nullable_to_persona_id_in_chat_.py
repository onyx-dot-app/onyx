"""add nullable to persona id in Chat Session

Revision ID: c99d76fcd298
Revises: 5c7fdadae813
Create Date: 2024-07-09 19:27:01.579697

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c99d76fcd298"
down_revision = "5c7fdadae813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_session", "persona_id", existing_type=sa.INTEGER(), nullable=True
    )


def downgrade() -> None:
    # Delete chat messages and feedback first since they reference chat sessions
    # Get chat messages from sessions with null persona_id
    chat_messages_query = """
        SELECT id
        FROM chat_message
        WHERE chat_session_id IN (
            SELECT id
            FROM chat_session
            WHERE persona_id IS NULL
        )
    """

    # Delete dependent records first
    op.execute(
        f"""
        DELETE FROM document_retrieval_feedback
        WHERE chat_message_id IN (
            {chat_messages_query}
        )
    """
    )
    op.execute(
        f"""
        DELETE FROM chat_message__search_doc
        WHERE chat_message_id IN (
            {chat_messages_query}
        )
    """
    )

    # Delete chat messages
    op.execute(
        """
        DELETE FROM chat_message
        WHERE chat_session_id IN (
            SELECT id
            FROM chat_session
            WHERE persona_id IS NULL
        )
    """
    )

    # Now we can safely delete the chat sessions
    op.execute(
        """
        DELETE FROM chat_session
        WHERE persona_id IS NULL
    """
    )

    op.alter_column(
        "chat_session",
        "persona_id",
        existing_type=sa.INTEGER(),
        nullable=False,
    )
