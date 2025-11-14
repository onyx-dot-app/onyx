"""add cheat_sheet_context to user

Revision ID: 12h73u00mcwb
Revises: a4f23d6b71c8
Create Date: 2025-11-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "12h73u00mcwb"
down_revision = "a4f23d6b71c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "cheat_sheet_context",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.create_table(
        "temporary_user_cheat_sheet_context",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("temporary_user_cheat_sheet_context")
    op.drop_column("user", "cheat_sheet_context")
