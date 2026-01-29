"""remove reranking from search_settings

Revision ID: 78ebc66946a0
Revises: 849b21c732f8
Create Date: 2026-01-28

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "78ebc66946a0"
down_revision = "849b21c732f8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("search_settings", "disable_rerank_for_streaming")
    op.drop_column("search_settings", "rerank_model_name")
    op.drop_column("search_settings", "rerank_provider_type")
    op.drop_column("search_settings", "rerank_api_key")
    op.drop_column("search_settings", "rerank_api_url")
    op.drop_column("search_settings", "num_rerank")


def downgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "disable_rerank_for_streaming",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "search_settings", sa.Column("rerank_model_name", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings", sa.Column("rerank_provider_type", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings", sa.Column("rerank_api_key", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings", sa.Column("rerank_api_url", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "num_rerank",
            sa.Integer(),
            nullable=False,
            server_default=str(20),
        ),
    )
