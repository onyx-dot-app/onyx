"""add accessibility preferences

Adds the motion, popup and dynamic conversation preferences a user picks in
Appearance settings.

Revision ID: f7b1d4c6e5a0
Revises: e6a0c3b5d4f9
Create Date: 2026-11-20 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7b1d4c6e5a0"
down_revision = "e6a0c3b5d4f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "motion",
            sa.String(length=7),
            nullable=False,
            server_default="system",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "popup_dismissal",
            sa.String(length=14),
            nullable=False,
            server_default="auto_dismiss",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "dynamic_conversations",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "dynamic_conversations")
    op.drop_column("user_preferences", "popup_dismissal")
    op.drop_column("user_preferences", "motion")
