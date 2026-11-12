"""add perm_sync_pending_since to cc_pair

Revision ID: 14846d586881
Revises: b88ad1941716
Create Date: 2026-10-05 18:10:41.302117

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "14846d586881"
down_revision = "b88ad1941716"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL means the pair does not wait for a permission sync.
    op.add_column(
        "connector_credential_pair",
        sa.Column("perm_sync_pending_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "perm_sync_pending_since")
