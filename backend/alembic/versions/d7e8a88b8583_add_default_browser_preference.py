"""add default browser preference

Revision ID: d7e8a88b8583
Revises: 00a73eb4dccf
Create Date: 2026-11-27 15:55:41.769266

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d7e8a88b8583"
down_revision = "00a73eb4dccf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "default_browser",
            sa.String(),
            nullable=False,
            server_default="SANDBOX",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "default_browser")
