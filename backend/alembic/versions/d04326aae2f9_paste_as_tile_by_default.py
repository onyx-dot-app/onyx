"""paste as tile by default

Revision ID: d04326aae2f9
Revises: ce6d912380d7
Create Date: 2026-11-25 11:46:05.220900

Turns on paste_as_tile for every user. The old default was false, and a saved
false cannot be told apart from the default, so all rows flip to true.
Downgrade restores the false default only.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d04326aae2f9"
down_revision = "ce6d912380d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_preferences",
        "paste_as_tile",
        server_default=sa.text("true"),
    )
    op.execute("UPDATE user_preferences SET paste_as_tile = true")


def downgrade() -> None:
    op.alter_column(
        "user_preferences",
        "paste_as_tile",
        server_default=sa.text("false"),
    )
