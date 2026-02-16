"""add chat_background to user

Revision ID: fb80bdd256de
Revises: 8b5ce697290e
Create Date: 2026-01-16 16:15:59.222617

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fb80bdd256de"
down_revision = "8b5ce697290e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "chat_background",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "chat_background")
