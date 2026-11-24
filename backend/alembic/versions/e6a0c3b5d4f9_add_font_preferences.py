"""add font preferences

Adds the interface and response font a user picks in Appearance settings.

Revision ID: e6a0c3b5d4f9
Revises: c4e8a1f3b2d7
Create Date: 2026-11-20 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6a0c3b5d4f9"
down_revision = "c4e8a1f3b2d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "interface_font",
            sa.String(length=12),
            nullable=False,
            server_default="default",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "response_font",
            sa.String(length=7),
            nullable=False,
            server_default="match",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "response_font")
    op.drop_column("user_preferences", "interface_font")
