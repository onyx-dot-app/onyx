"""Add is_public to mcp_server

Revision ID: b7e9a3c1d2f4
Revises: 8f2c4a1d9e3b
Create Date: 2026-06-18 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7e9a3c1d2f4"
down_revision = "8f2c4a1d9e3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing servers stay accessible to everyone (server_default true).
    op.add_column(
        "mcp_server",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "is_public")
