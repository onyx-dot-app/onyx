"""enable contextual retrieval

Revision ID: 8e1ac4f39a9f
Revises: 9aadf32dfeb4
Create Date: 2024-12-20 13:29:09.918661

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8e1ac4f39a9f"
down_revision = "9aadf32dfeb4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "enable_contextual_rag",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "contextual_rag_llm_name",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "contextual_rag_llm_provider",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("search_settings", "enable_contextual_rag")
    op.drop_column("search_settings", "contextual_rag_llm_name")
    op.drop_column("search_settings", "contextual_rag_llm_provider")
