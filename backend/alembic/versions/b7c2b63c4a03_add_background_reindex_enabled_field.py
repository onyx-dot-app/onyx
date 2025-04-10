"""add background_reindex_enabled field

Revision ID: b7c2b63c4a03
Revises: f11b408e39d3
Create Date: 2024-03-26 12:34:56.789012

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.enums import EmbeddingPrecision


# revision identifiers, used by Alembic.
revision = "b7c2b63c4a03"
down_revision = "f11b408e39d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add background_reindex_enabled column with default value of True
    op.add_column(
        "search_settings",
        sa.Column(
            "background_reindex_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # Add embedding_precision column with default value of FLOAT
    op.add_column(
        "search_settings",
        sa.Column(
            "embedding_precision",
            sa.Enum(EmbeddingPrecision, native_enum=False),
            nullable=False,
            server_default=EmbeddingPrecision.FLOAT.name,
        ),
    )

    # Add reduced_dimension column with default value of None
    op.add_column(
        "search_settings",
        sa.Column("reduced_dimension", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # Remove the background_reindex_enabled column
    op.drop_column("search_settings", "background_reindex_enabled")
    op.drop_column("search_settings", "embedding_precision")
    op.drop_column("search_settings", "reduced_dimension")
