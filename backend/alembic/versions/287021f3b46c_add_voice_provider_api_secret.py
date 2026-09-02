"""add voice provider api secret

Revision ID: 287021f3b46c
Revises: 34fe28843029
Create Date: 2026-08-27 10:38:32.439483

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "287021f3b46c"
down_revision = "34fe28843029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice_provider",
        sa.Column("api_secret", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_provider", "api_secret")
