"""add background_reindex_enabled field

Revision ID: b7c2b63c4a03
Revises: f11b408e39d3
Create Date: 2024-03-26 12:34:56.789012

"""
from alembic import op
import sqlalchemy as sa


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


def downgrade() -> None:
    # Remove the background_reindex_enabled column
    op.drop_column("search_settings", "background_reindex_enabled")
