"""added slack_auto_filter

Revision ID: 7aea705850d5
Revises: 4505fd7302e1
Create Date: 2024-07-10 11:01:23.581015

"""

from alembic import op
import sqlalchemy as sa

revision = "7aea705850d5"
down_revision = "4505fd7302e1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "slack_bot_config",
        sa.Column("enable_auto_filters", sa.Boolean(), nullable=True),
    )
    op.execute(
        "UPDATE slack_bot_config SET enable_auto_filters = FALSE WHERE enable_auto_filters IS NULL"
    )
    op.alter_column(
        "slack_bot_config",
        "enable_auto_filters",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.drop_column("slack_bot_config", "enable_auto_filters")
