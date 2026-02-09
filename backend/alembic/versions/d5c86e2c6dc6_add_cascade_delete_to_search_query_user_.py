"""add_cascade_delete_to_search_query_user_id

Revision ID: d5c86e2c6dc6
Revises: 90b409d06e50
Create Date: 2026-02-04 16:05:04.749804

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d5c86e2c6dc6"
down_revision = "90b409d06e50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("search_query_user_id_fkey", "search_query", type_="foreignkey")
    op.create_foreign_key(
        "search_query_user_id_fkey",
        "search_query",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("search_query_user_id_fkey", "search_query", type_="foreignkey")
    op.create_foreign_key(
        "search_query_user_id_fkey", "search_query", "user", ["user_id"], ["id"]
    )
