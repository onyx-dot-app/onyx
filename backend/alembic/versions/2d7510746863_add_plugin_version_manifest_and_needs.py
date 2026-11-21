"""add plugin version manifest and needs

A plugin version keeps the plugin.json fields Onyx shows and the MCP servers
its plugin needs. Both are NULL for a skill version.

Revision ID: 2d7510746863
Revises: 7a3c9e5b1d08
Create Date: 2026-11-19 10:12:41.903617

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2d7510746863"
down_revision = "7a3c9e5b1d08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugin_version",
        sa.Column("manifest", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "plugin_version",
        sa.Column("needs", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plugin_version", "needs")
    op.drop_column("plugin_version", "manifest")
