"""add_user_preferences

Revision ID: 175ea04c7087
Revises: d56ffa94ca32
Create Date: 2026-02-04 18:16:24.830873

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "175ea04c7087"
down_revision = "d56ffa94ca32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("user_preferences", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "user_preferences")
