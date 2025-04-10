"""add support for litellm proxy in reranking

Revision ID: ba98eba0f66a
Revises: bceb1e139447
Create Date: 2024-09-06 10:36:04.507332

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ba98eba0f66a"
down_revision = "bceb1e139447"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "search_settings", sa.Column("rerank_api_url", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("search_settings", "rerank_api_url")
