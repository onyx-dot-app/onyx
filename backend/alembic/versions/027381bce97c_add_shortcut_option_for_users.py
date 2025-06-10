"""add shortcut option for users

Revision ID: 027381bce97c
Revises: 6fc7886d665d
Create Date: 2025-01-14 12:14:00.814390

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "027381bce97c"
down_revision = "6fc7886d665d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "shortcut_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "shortcut_enabled")
