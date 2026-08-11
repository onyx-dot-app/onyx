"""add incognito_enabled to user_group

Revision ID: 1d32626a7bbb
Revises: 0ec213a5ffde
Create Date: 2026-08-10 16:07:14.175959

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1d32626a7bbb"
down_revision = "0ec213a5ffde"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_group",
        sa.Column(
            "incognito_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_group", "incognito_enabled")
