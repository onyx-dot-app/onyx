"""add pending backfills and full re-index requests

Revision ID: 078171a436f9
Revises: 90dceb6cd426
Create Date: 2026-10-06 07:37:53.977280

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "078171a436f9"
down_revision = "90dceb6cd426"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An empty list means no backfill waits; existing pairs start with none.
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "pending_backfills",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Nullable: NULL means no request is pending.
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "full_reindex_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "full_reindex_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "full_reindex_requested_at")
    op.drop_column("connector_credential_pair", "full_reindex_requested_at")
    op.drop_column("connector_credential_pair", "pending_backfills")
