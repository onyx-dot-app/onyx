"""properly_cascade

Revision ID: 35e518e0ddf4
Revises: 91a0a4d62b14
Create Date: 2024-09-20 21:24:04.891018

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "35e518e0ddf4"
down_revision = "91a0a4d62b14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update chat_message foreign key constraint
    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )
    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Update chat_message__search_doc foreign key constraints
    op.drop_constraint(
        "chat_message__search_doc_chat_message_id_fkey",
        "chat_message__search_doc",
        type_="foreignkey",
    )
    op.drop_constraint(
        "chat_message__search_doc_search_doc_id_fkey",
        "chat_message__search_doc",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "chat_message__search_doc_chat_message_id_fkey",
        "chat_message__search_doc",
        "chat_message",
        ["chat_message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "chat_message__search_doc_search_doc_id_fkey",
        "chat_message__search_doc",
        "search_doc",
        ["search_doc_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add CASCADE delete for tool_call foreign key
    op.drop_constraint("tool_call_message_id_fkey", "tool_call", type_="foreignkey")
    op.create_foreign_key(
        "tool_call_message_id_fkey",
        "tool_call",
        "chat_message",
        ["message_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Revert chat_message foreign key constraint
    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )
    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["id"],
    )

    # Revert chat_message__search_doc foreign key constraints
    op.drop_constraint(
        "chat_message__search_doc_chat_message_id_fkey",
        "chat_message__search_doc",
        type_="foreignkey",
    )
    op.drop_constraint(
        "chat_message__search_doc_search_doc_id_fkey",
        "chat_message__search_doc",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "chat_message__search_doc_chat_message_id_fkey",
        "chat_message__search_doc",
        "chat_message",
        ["chat_message_id"],
        ["id"],
    )
    op.create_foreign_key(
        "chat_message__search_doc_search_doc_id_fkey",
        "chat_message__search_doc",
        "search_doc",
        ["search_doc_id"],
        ["id"],
    )

    # Revert tool_call foreign key constraint
    op.drop_constraint("tool_call_message_id_fkey", "tool_call", type_="foreignkey")
    op.create_foreign_key(
        "tool_call_message_id_fkey",
        "tool_call",
        "chat_message",
        ["message_id"],
        ["id"],
    )
