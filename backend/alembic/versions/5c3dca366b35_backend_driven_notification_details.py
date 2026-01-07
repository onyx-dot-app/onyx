"""backend driven notification details

Revision ID: 5c3dca366b35
Revises: 9a0296d7421e
Create Date: 2026-01-06 16:03:11.413724

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5c3dca366b35"
down_revision = "9a0296d7421e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column(
            "title", sa.String(), nullable=False, server_default="New Notification"
        ),
    )
    op.add_column(
        "notification",
        sa.Column("description", sa.String(), nullable=True, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("notification", "title")
    op.drop_column("notification", "description")
