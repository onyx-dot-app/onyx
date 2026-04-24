"""add paste_as_tile to user

Revision ID: 74379b447d4c
Revises: a7c3e2b1d4f8
Create Date: 2026-04-23 18:30:42.452355

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "74379b447d4c"
down_revision = "a7c3e2b1d4f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "paste_as_tile", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "paste_as_tile")
