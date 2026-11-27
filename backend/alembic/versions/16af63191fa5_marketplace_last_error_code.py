"""marketplace last error code

Revision ID: 16af63191fa5
Revises: 00a73eb4dccf
Create Date: 2026-11-27 10:00:00.000000

The code and reset time of the last sync error, so the client can translate it.
"""

from alembic import op
import sqlalchemy as sa

revision = "16af63191fa5"
down_revision = "00a73eb4dccf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugin_marketplace",
        sa.Column("last_error_code", sa.String(), nullable=True),
    )
    op.add_column(
        "plugin_marketplace",
        sa.Column("last_error_reset_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plugin_marketplace", "last_error_reset_at")
    op.drop_column("plugin_marketplace", "last_error_code")
