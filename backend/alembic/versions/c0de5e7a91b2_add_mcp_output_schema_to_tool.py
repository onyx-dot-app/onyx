"""add mcp_output_schema to tool

The output schema that an MCP server declares for a tool. Code mode types the
tool's result from it.

Revision ID: c0de5e7a91b2
Revises: c3e8a1f5d702
Create Date: 2026-11-02 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c0de5e7a91b2"
down_revision = "c3e8a1f5d702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column("mcp_output_schema", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool", "mcp_output_schema")
