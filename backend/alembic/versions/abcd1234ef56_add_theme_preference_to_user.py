"""add_theme_preference_to_user

Revision ID: abcd1234ef56
Revises: 3d1cca026fe8
Create Date: 2025-10-24 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "abcd1234ef56"
down_revision = "3d1cca026fe8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "theme_preference",
            sa.String(),
            nullable=False,
            server_default="system",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "theme_preference")
