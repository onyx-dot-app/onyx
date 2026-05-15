"""replace document sync index with partial index

Replaces the composite index ix_document_sync_status (last_modified, last_synced)
with a partial index ix_document_needs_sync that only indexes rows where
last_modified > last_synced OR last_synced IS NULL.

The old index was never used by the query planner (0 scans in pg_stat_user_indexes)
because Postgres cannot use a B-tree composite index to evaluate a comparison
between two columns in the same row combined with an OR/IS NULL condition.

The partial index makes count_documents_by_needs_sync ~4000x faster for tenants
with no stale documents (161ms -> 0.04ms on a 929K row table) and ~17x faster
for tenants with large backlogs (846ms -> 50ms on a 164K row table).

Revision ID: a6fcd3d631f9
Revises: d129f37b3d87
Create Date: 2026-04-17 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a6fcd3d631f9"
down_revision = "d129f37b3d87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_document_needs_sync",
        "document",
        ["id"],
        postgresql_where=sa.text("last_modified > last_synced OR last_synced IS NULL"),
    )
    op.drop_index("ix_document_sync_status", table_name="document")


def downgrade() -> None:
    op.create_index(
        "ix_document_sync_status",
        "document",
        ["last_modified", "last_synced"],
    )
    op.drop_index("ix_document_needs_sync", table_name="document")
