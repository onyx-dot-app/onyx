"""add last_auth_failure_at to mcp_connection_config

Revision ID: 12cf8a96ae98
Revises: f3a9c1d4b7e2
Create Date: 2026-06-15 15:23:48.360683

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "12cf8a96ae98"
down_revision = "f3a9c1d4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_connection_config",
        sa.Column(
            "last_auth_failure_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_connection_config", "last_auth_failure_at")
