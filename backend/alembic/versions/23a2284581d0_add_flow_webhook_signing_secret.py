"""Add the per-flow webhook signing secret

Revision ID: 23a2284581d0
Revises: c3a81d6f4e27
Create Date: 2026-06-03 16:48:19.340226

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "23a2284581d0"
down_revision = "c3a81d6f4e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, and left NULL for flows that already exist. A flow mints one
    # the first time it is asked for, so nothing has to be backfilled and no
    # existing flow gains a secret it never uses.
    op.add_column(
        "flow",
        sa.Column(
            "webhook_signing_secret", sa.LargeBinary(), nullable=True
        ),  # EncryptedString
    )


def downgrade() -> None:
    op.drop_column("flow", "webhook_signing_secret")
