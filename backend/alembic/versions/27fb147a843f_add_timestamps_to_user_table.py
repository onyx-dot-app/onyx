"""add timestamps to user table

Revision ID: 27fb147a843f
Revises: a3b8d9e2f1c4
Create Date: 2026-03-08 17:18:40.828644

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "27fb147a843f"
down_revision = "a3b8d9e2f1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "updated_at")
    op.drop_column("user", "created_at")
