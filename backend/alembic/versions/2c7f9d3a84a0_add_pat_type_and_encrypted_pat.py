"""add pat_type and encrypted_pat

Revision ID: 2c7f9d3a84a0
Revises: 4ff2545411ad
Create Date: 2026-05-12 12:05:32.340868

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2c7f9d3a84a0"
down_revision = "4ff2545411ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_access_token",
        sa.Column("pat_type", sa.String(), nullable=False, server_default="USER"),
    )
    op.add_column(
        "sandbox",
        sa.Column("encrypted_pat", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sandbox", "encrypted_pat")
    op.drop_column("personal_access_token", "pat_type")
