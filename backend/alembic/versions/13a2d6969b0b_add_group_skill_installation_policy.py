"""add group skill installation policy

Revision ID: 13a2d6969b0b
Revises: c3e8a1f5d702
Create Date: 2026-11-07 13:02:58.420714

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "13a2d6969b0b"
down_revision = "c3e8a1f5d702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill__user_group",
        sa.Column("installation_policy", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill__user_group", "installation_policy")
