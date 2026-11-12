"""add prune request fields to cc_pair and index_attempt

Revision ID: b88ad1941716
Revises: c842ec4b17f4
Create Date: 2026-10-05 17:05:12.418211

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b88ad1941716"
down_revision = "c842ec4b17f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL means no request is pending.
    op.add_column(
        "connector_credential_pair",
        sa.Column("prune_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "prune_after_reindex_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "prune_after_reindex_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "prune_after_reindex_requested_at")
    op.drop_column("connector_credential_pair", "prune_after_reindex_requested_at")
    op.drop_column("connector_credential_pair", "prune_requested_at")
