"""add user language preference

Revision ID: 99c855a8f2a1
Revises: f3a9c1d4b7e2
Create Date: 2026-06-22 15:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "99c855a8f2a1"
down_revision = "f3a9c1d4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "language",
            sa.String(),
            nullable=False,
            server_default="en",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "language")
