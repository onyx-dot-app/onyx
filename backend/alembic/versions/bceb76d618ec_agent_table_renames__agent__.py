"""agent_table_renames__agent__

Revision ID: bceb76d618ec
Revises: c0132518a25b
Create Date: 2025-01-06 10:50:48.109285

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "bceb76d618ec"
down_revision = "c0132518a25b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "sub_query__search_doc_sub_query_id_fkey",
        "sub_query__search_doc",
        type_="foreignkey",
    )
    op.drop_constraint(
        "sub_query__search_doc_search_doc_id_fkey",
        "sub_query__search_doc",
        type_="foreignkey",
    )
    # Rename tables
    op.rename_table("sub_query", "agent__sub_query")
    op.rename_table("sub_question", "agent__sub_question")
    op.rename_table("sub_query__search_doc", "agent__sub_query__search_doc")

    # Update both foreign key constraints for agent__sub_query__search_doc

    # Create new foreign keys with updated names
    op.create_foreign_key(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        "agent__sub_query",
        ["sub_query_id"],
        ["id"],
    )
    op.create_foreign_key(
        "agent__sub_query__search_doc_search_doc_id_fkey",
        "agent__sub_query__search_doc",
        "search_doc",  # This table name doesn't change
        ["search_doc_id"],
        ["id"],
    )


def downgrade() -> None:
    # Update foreign key constraints for sub_query__search_doc
    op.drop_constraint(
        "agent__sub_query__search_doc_sub_query_id_fkey",
        "agent__sub_query__search_doc",
        type_="foreignkey",
    )
    op.drop_constraint(
        "agent__sub_query__search_doc_search_doc_id_fkey",
        "agent__sub_query__search_doc",
        type_="foreignkey",
    )

    # Rename tables back
    op.rename_table("agent__sub_query__search_doc", "sub_query__search_doc")
    op.rename_table("agent__sub_question", "sub_question")
    op.rename_table("agent__sub_query", "sub_query")

    op.create_foreign_key(
        "sub_query__search_doc_sub_query_id_fkey",
        "sub_query__search_doc",
        "sub_query",
        ["sub_query_id"],
        ["id"],
    )
    op.create_foreign_key(
        "sub_query__search_doc_search_doc_id_fkey",
        "sub_query__search_doc",
        "search_doc",  # This table name doesn't change
        ["search_doc_id"],
        ["id"],
    )
