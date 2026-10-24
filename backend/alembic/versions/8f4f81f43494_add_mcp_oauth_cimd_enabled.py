"""add mcp oauth cimd enabled

Revision ID: 8f4f81f43494
Revises: c7e1a2f4b9d3
Create Date: 2026-10-19 06:55:25.738614

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8f4f81f43494"
down_revision = "c7e1a2f4b9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server",
        sa.Column(
            "oauth_cimd_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "oauth_cimd_enabled")
