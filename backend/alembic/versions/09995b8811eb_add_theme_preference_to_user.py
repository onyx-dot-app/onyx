"""add theme_preference to user

Revision ID: 09995b8811eb
Revises: 3d1cca026fe8
Create Date: 2025-10-24 08:58:50.246949

"""

from alembic import op
import sqlalchemy as sa
from onyx.db.enums import ThemePreference


# revision identifiers, used by Alembic.
revision = "09995b8811eb"
down_revision = "3d1cca026fe8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "theme_preference",
            sa.Enum(ThemePreference, native_enum=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "theme_preference")
