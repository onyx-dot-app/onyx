"""nullable preferences

Revision ID: b388730a2899
Revises: b7a7eee5aa15
Create Date: 2025-02-17 18:49:22.643902

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "b388730a2899"
down_revision = "b7a7eee5aa15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user", "temperature_override_enabled", nullable=True)
    op.alter_column("user", "auto_scroll", nullable=True)


def downgrade() -> None:
    op.alter_column("user", "temperature_override_enabled", nullable=False)
    op.alter_column("user", "auto_scroll", nullable=False)
