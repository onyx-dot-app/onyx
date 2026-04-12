"""Add language_preference to user

Revision ID: a3b2c1d4e5f6
Revises: f1ca58b2f2ec
Create Date: 2026-04-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a3b2c1d4e5f6"
down_revision: str | None = "f1ca58b2f2ec"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "language_preference",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "language_preference")
