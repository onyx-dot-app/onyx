"""drop embedding_precision from search_settings

Revision ID: 219b8d718c0c
Revises: 890a8be0ea88
Create Date: 2026-09-29 12:41:38.910336

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "219b8d718c0c"
down_revision = "890a8be0ea88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only the unused Vespa index read this column. OpenSearch always stores
    # float32 vectors; see vector_quantization instead.
    op.drop_column("search_settings", "embedding_precision")


def downgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "embedding_precision",
            sa.String(length=8),
            nullable=False,
            server_default="FLOAT",
        ),
    )
