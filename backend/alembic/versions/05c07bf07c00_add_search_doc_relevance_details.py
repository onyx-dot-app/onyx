"""add search doc relevance details

Revision ID: 05c07bf07c00
Revises: b896bbd0d5a7
Create Date: 2024-07-10 17:48:15.886653

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "05c07bf07c00"
down_revision = "b896bbd0d5a7"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "search_doc",
        sa.Column("is_relevant", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "search_doc",
        sa.Column("relevance_explanation", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_doc", "relevance_explanation")
    op.drop_column("search_doc", "is_relevant")
