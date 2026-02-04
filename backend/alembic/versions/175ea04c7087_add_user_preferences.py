"""add_user_preferences

Revision ID: 175ea04c7087
Revises: 90b409d06e50
Create Date: 2026-02-04 18:16:24.830873

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "175ea04c7087"
down_revision = "90b409d06e50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("user_preferences", sa.Text(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "use_user_preferences",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "use_user_preferences")
    op.drop_column("user", "user_preferences")
