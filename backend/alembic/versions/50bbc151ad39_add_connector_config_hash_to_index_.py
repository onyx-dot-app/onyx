"""add connector_config_hash to index_attempt

Revision ID: 50bbc151ad39
Revises: e22aca06966a
Create Date: 2026-10-05 15:59:43.922809

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "50bbc151ad39"
down_revision = "e22aca06966a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable without a backfill: existing attempts have no known config hash,
    # and a NULL hash keeps their checkpoints reusable.
    op.add_column(
        "index_attempt",
        sa.Column("connector_config_hash", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "connector_config_hash")
