"""add stdio config to mcp server

Revision ID: 4c8e1a7d2b6f
Revises: f57f35403f6c
Create Date: 2026-07-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "4c8e1a7d2b6f"
down_revision = "f57f35403f6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_server", sa.Column("stdio_command", sa.Text(), nullable=True))
    op.add_column(
        "mcp_server",
        sa.Column("stdio_args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "stdio_args")
    op.drop_column("mcp_server", "stdio_command")
