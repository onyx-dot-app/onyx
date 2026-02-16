"""add_search_query_table

Revision ID: 73e9983e5091
Revises: d1b637d7050a
Create Date: 2026-01-14 14:16:52.837489

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "73e9983e5091"
down_revision = "d1b637d7050a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_query",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("query_expansions", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_search_query_user_id", "search_query", ["user_id"])
    op.create_index("ix_search_query_created_at", "search_query", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_search_query_created_at", table_name="search_query")
    op.drop_index("ix_search_query_user_id", table_name="search_query")
    op.drop_table("search_query")
