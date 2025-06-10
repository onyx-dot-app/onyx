"""nullable preferences

Revision ID: b388730a2899
Revises: 1a03d2c2856b
Create Date: 2025-02-17 18:49:22.643902

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b388730a2899"
down_revision = "1a03d2c2856b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user", "temperature_override_enabled", nullable=True)
    op.alter_column("user", "auto_scroll", nullable=True)


def downgrade() -> None:
    # Ensure no null values before making columns non-nullable
    op.execute(
        'UPDATE "user" SET temperature_override_enabled = false WHERE temperature_override_enabled IS NULL'
    )
    op.execute('UPDATE "user" SET auto_scroll = false WHERE auto_scroll IS NULL')

    op.alter_column("user", "temperature_override_enabled", nullable=False)
    op.alter_column("user", "auto_scroll", nullable=False)
