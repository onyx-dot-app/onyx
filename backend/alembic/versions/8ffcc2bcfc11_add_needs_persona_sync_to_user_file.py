"""add needs_persona_sync to user_file

Revision ID: 8ffcc2bcfc11
Revises: 7616121f6e97
Create Date: 2026-02-23 10:48:48.343826

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8ffcc2bcfc11"
down_revision = "7616121f6e97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_file",
        sa.Column(
            "needs_persona_sync",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_file", "needs_persona_sync")
