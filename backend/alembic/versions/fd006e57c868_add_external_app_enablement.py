"""Add external app enablement.

Revision ID: fd006e57c868
Revises: 9cc89a7b96de
Create Date: 2026-07-17 13:24:43.117490

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fd006e57c868"
down_revision = "9cc89a7b96de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_app",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("external_app", "enabled")
