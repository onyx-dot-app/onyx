"""Record marketplace webhook ref and delivery time

Revision ID: 8fc170c91f59
Revises: 54013115725e
Create Date: 2026-11-08 06:28:35.802768

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8fc170c91f59"
down_revision = "54013115725e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("marketplace", sa.Column("webhook_ref", sa.String(), nullable=True))
    op.add_column(
        "marketplace",
        sa.Column(
            "webhook_last_delivery_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace", "webhook_last_delivery_at")
    op.drop_column("marketplace", "webhook_ref")
