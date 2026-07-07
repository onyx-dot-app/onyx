"""add craft_enabled to user

Revision ID: 8c8ff08f8035
Revises: 20f09b642ed0
Create Date: 2026-07-07 14:55:11.241402

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8c8ff08f8035"
down_revision = "20f09b642ed0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("craft_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("user", "craft_enabled")
