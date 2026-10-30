"""add document secondary content hash

Revision ID: b2785b68357b
Revises: 3e30a81ec3bd
Create Date: 2026-10-28 18:45:54.192296

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2785b68357b"
down_revision = "3e30a81ec3bd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document", sa.Column("secondary_content_hash", sa.String(), nullable=True)
    )
    op.add_column(
        "document",
        sa.Column("secondary_search_settings_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "secondary_search_settings_id")
    op.drop_column("document", "secondary_content_hash")
