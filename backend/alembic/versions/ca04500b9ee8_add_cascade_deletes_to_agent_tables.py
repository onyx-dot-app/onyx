"""add_cascade_deletes_to_agent_tables

Revision ID: ca04500b9ee8
Revises: 238b84885828
Create Date: 2025-05-30 16:03:51.112263

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "ca04500b9ee8"
down_revision = "238b84885828"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing foreign key constraints
    op.drop_constraint(
        "agent__sub_question_primary_question_id_fkey",
        "agent__sub_question",
        type_="foreignkey",
    )
    op.drop_constraint(
        "agent__sub_query_parent_question_id_fkey",
        "agent__sub_query",
        type_="foreignkey",
    )
    op.drop_constraint(
        "chat_message__standard_answer_chat_message_id_fkey",
        "chat_message__standard_answer",
        type_="foreignkey",
    )
    op.drop_constraint(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        type_="foreignkey",
    )

    # Recreate foreign key constraints with CASCADE delete
    op.create_foreign_key(
        "agent__sub_question_primary_question_id_fkey",
        "agent__sub_question",
        "chat_message",
        ["primary_question_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "agent__sub_query_parent_question_id_fkey",
        "agent__sub_query",
        "agent__sub_question",
        ["parent_question_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "chat_message__standard_answer_chat_message_id_fkey",
        "chat_message__standard_answer",
        "chat_message",
        ["chat_message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        "agent__sub_query",
        ["sub_query_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop CASCADE foreign key constraints
    op.drop_constraint(
        "agent__sub_question_primary_question_id_fkey",
        "agent__sub_question",
        type_="foreignkey",
    )
    op.drop_constraint(
        "agent__sub_query_parent_question_id_fkey",
        "agent__sub_query",
        type_="foreignkey",
    )
    op.drop_constraint(
        "chat_message__standard_answer_chat_message_id_fkey",
        "chat_message__standard_answer",
        type_="foreignkey",
    )
    op.drop_constraint(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        type_="foreignkey",
    )

    # Recreate foreign key constraints without CASCADE delete
    op.create_foreign_key(
        "agent__sub_question_primary_question_id_fkey",
        "agent__sub_question",
        "chat_message",
        ["primary_question_id"],
        ["id"],
    )
    op.create_foreign_key(
        "agent__sub_query_parent_question_id_fkey",
        "agent__sub_query",
        "agent__sub_question",
        ["parent_question_id"],
        ["id"],
    )
    op.create_foreign_key(
        "chat_message__standard_answer_chat_message_id_fkey",
        "chat_message__standard_answer",
        "chat_message",
        ["chat_message_id"],
        ["id"],
    )
    op.create_foreign_key(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        "agent__sub_query",
        ["sub_query_id"],
        ["id"],
    )
