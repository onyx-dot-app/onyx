"""replace embedding_precision with vector_quantization on search_settings

Revision ID: 890a8be0ea88
Revises: 25053020dd5a
Create Date: 2026-09-28 17:52:08.888885

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "890a8be0ea88"
down_revision = "25053020dd5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing indices have no quantization in their mapping.
    op.add_column(
        "search_settings",
        sa.Column(
            "vector_quantization",
            sa.Enum(
                "NONE",
                "SCALAR_7_BIT",
                "SCALAR_1_BIT",
                name="vectorquantization",
                native_enum=False,
            ),
            nullable=False,
            server_default="NONE",
        ),
    )
    # Only the unused Vespa index read this column. OpenSearch always stores
    # float32 vectors.
    op.drop_column("search_settings", "embedding_precision")


def downgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "embedding_precision",
            sa.Enum(
                "BFLOAT16",
                "FLOAT",
                name="embeddingprecision",
                native_enum=False,
            ),
            nullable=False,
            server_default="FLOAT",
        ),
    )
    op.drop_column("search_settings", "vector_quantization")
