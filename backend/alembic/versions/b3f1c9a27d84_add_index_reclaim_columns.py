"""add index reclaim columns

Revision ID: b3f1c9a27d84
Revises: ea9771dd828c
Create Date: 2026-07-23 00:00:00.000000

Additive old-index-reclamation columns on search_settings (post-reindex deletion of
the now-PAST index + the consented not-ported cc_pair deletions). All nullable /
defaulted, so no backfill; existing rows stay reclaim_status=NULL (not auto-reclaimed).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.db.enums import IndexReclaimStatus

# revision identifiers, used by Alembic.
revision = "b3f1c9a27d84"
down_revision = "ea9771dd828c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "reclaim_status",
            sa.Enum(IndexReclaimStatus, native_enum=False),
            nullable=True,
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "reclaim_stopped_reading_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "reclaim_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column("reclaim_last_error", sa.String(), nullable=True),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "pending_cc_pair_deletions",
            postgresql.ARRAY(sa.Integer()),
            nullable=True,
        ),
    )
    # Scan predicate for the reclaim beat task: PAST rows still needing cleanup.
    op.create_index(
        "ix_search_settings_reclaimable",
        "search_settings",
        ["reclaim_status"],
        unique=False,
        postgresql_where=sa.text("status = 'PAST'"),
    )


def downgrade() -> None:
    op.drop_index("ix_search_settings_reclaimable", table_name="search_settings")
    op.drop_column("search_settings", "pending_cc_pair_deletions")
    op.drop_column("search_settings", "reclaim_last_error")
    op.drop_column("search_settings", "reclaim_attempts")
    op.drop_column("search_settings", "reclaim_stopped_reading_at")
    op.drop_column("search_settings", "reclaim_status")
