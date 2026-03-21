"""add_opensearch_tenant_migration_columns

Revision ID: feead2911109
Revises: d56ffa94ca32
Create Date: 2026-02-10 17:46:34.029937

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "feead2911109"
down_revision = "175ea04c7087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE opensearch_tenant_migration_record "
        "ADD COLUMN IF NOT EXISTS vespa_visit_continuation_token TEXT"
    )
    op.execute(
        "ALTER TABLE opensearch_tenant_migration_record "
        "ADD COLUMN IF NOT EXISTS total_chunks_migrated INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE opensearch_tenant_migration_record "
        "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )
    op.execute(
        "ALTER TABLE opensearch_tenant_migration_record "
        "ADD COLUMN IF NOT EXISTS migration_completed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE opensearch_tenant_migration_record "
        "ADD COLUMN IF NOT EXISTS enable_opensearch_retrieval BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.drop_column("opensearch_tenant_migration_record", "enable_opensearch_retrieval")
    op.drop_column("opensearch_tenant_migration_record", "migration_completed_at")
    op.drop_column("opensearch_tenant_migration_record", "created_at")
    op.drop_column("opensearch_tenant_migration_record", "total_chunks_migrated")
    op.drop_column(
        "opensearch_tenant_migration_record", "vespa_visit_continuation_token"
    )
