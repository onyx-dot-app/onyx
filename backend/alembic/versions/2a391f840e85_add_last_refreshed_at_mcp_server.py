"""add last refreshed at mcp server

Revision ID: 2a391f840e85
Revises: 18b5b2524446
Create Date: 2025-12-06 15:19:59.766066

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembi.
revision = "2a391f840e85"
down_revision = "18b5b2524446"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server",
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "last_refreshed_at")
