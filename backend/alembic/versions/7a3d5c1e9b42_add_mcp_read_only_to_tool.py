"""add mcp_read_only to tool

The readOnlyHint that an MCP server declares for a tool. NULL means the server
gave no hint. A read-only tool defaults to the ALWAYS action policy.

Revision ID: 7a3d5c1e9b42
Revises: 2f930589ddab
Create Date: 2026-11-12 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a3d5c1e9b42"
down_revision = "2f930589ddab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool", sa.Column("mcp_read_only", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool", "mcp_read_only")
