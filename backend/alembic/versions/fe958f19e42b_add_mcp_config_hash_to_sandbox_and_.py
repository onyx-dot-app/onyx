"""add mcp_config_hash to sandbox and build_session

Revision ID: fe958f19e42b
Revises: ea9771dd828c
Create Date: 2026-07-22 17:36:56.749604

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fe958f19e42b"
down_revision = "ea9771dd828c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox",
        sa.Column("mcp_config_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "build_session",
        sa.Column("mcp_config_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("build_session", "mcp_config_hash")
    op.drop_column("sandbox", "mcp_config_hash")
