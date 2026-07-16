"""add craft_enabled to user

Revision ID: 8c8ff08f8035
Revises: 1fc2904131a3
Create Date: 2026-07-07 14:55:11.241402

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8c8ff08f8035"
down_revision = "1fc2904131a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = follow the workspace default.
    op.add_column(
        "user",
        sa.Column("craft_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "craft_enabled")
