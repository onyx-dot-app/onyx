"""add missing FK indexes for hot tables

Adds indexes on foreign key columns that are frequently queried by celery
worker tasks but were missing indexes, causing full sequential scans.

Postgres does NOT automatically create indexes on foreign key columns
(unlike MySQL). These four columns were identified via Aurora Performance
Insights as the top contributors to primary-worker AAS after the
ix_document_needs_sync partial index was deployed.

- index_attempt_errors.index_attempt_id: #1 query in pg_stat_statements
  (56ms mean on a 532K-row / 997MB table). Queried every check_for_indexing
  cycle to load errors per attempt.
- index_attempt_errors.connector_credential_pair_id: same table, queried
  when filtering errors by cc_pair.
- index_attempt.connector_credential_pair_id: queried by check_for_indexing
  to find attempts for each cc_pair. 73ms mean on tenant_dev.
- hierarchy_node.document_id: 18MB+ on large tenants, queried during
  document deletion and hierarchy rebuilds.

Note: Index names follow SQLAlchemy's ix_<table>_<column> convention to match
the `index=True` declarations in models.py. This prevents autogenerate from
detecting a mismatch and creating duplicate indexes.

Revision ID: 856bcbe14d79
Revises: a6fcd3d631f9
Create Date: 2026-04-19 18:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "856bcbe14d79"
down_revision = "91d150c361f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_index_attempt_errors_index_attempt_id",
        "index_attempt_errors",
        ["index_attempt_id"],
    )
    op.create_index(
        "ix_index_attempt_errors_connector_credential_pair_id",
        "index_attempt_errors",
        ["connector_credential_pair_id"],
    )
    op.create_index(
        "ix_index_attempt_connector_credential_pair_id",
        "index_attempt",
        ["connector_credential_pair_id"],
    )
    op.create_index(
        "ix_hierarchy_node_document_id",
        "hierarchy_node",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hierarchy_node_document_id", table_name="hierarchy_node")
    op.drop_index(
        "ix_index_attempt_connector_credential_pair_id", table_name="index_attempt"
    )
    op.drop_index(
        "ix_index_attempt_errors_connector_credential_pair_id",
        table_name="index_attempt_errors",
    )
    op.drop_index(
        "ix_index_attempt_errors_index_attempt_id", table_name="index_attempt_errors"
    )
