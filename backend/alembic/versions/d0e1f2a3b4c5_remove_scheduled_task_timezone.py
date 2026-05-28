"""remove scheduled task timezone

Revision ID: d0e1f2a3b4c5
Revises: 39287906b97a
Create Date: 2026-05-25 09:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "39287906b97a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("scheduled_task", "timezone")


def downgrade() -> None:
    op.add_column(
        "scheduled_task",
        sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
    )
    op.alter_column("scheduled_task", "timezone", server_default=None)
