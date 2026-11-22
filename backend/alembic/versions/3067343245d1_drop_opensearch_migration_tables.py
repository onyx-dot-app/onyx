"""drop opensearch migration tables

These tables tracked the Vespa to OpenSearch migration. Every instance has
finished that migration, and nothing reads or writes the tables anymore.

Revision ID: 3067343245d1
Revises: b7c2e4f1a9d3
Create Date: 2026-09-30 13:47:48.331663

"""

import logging
import time

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "3067343245d1"
down_revision = "b7c2e4f1a9d3"
branch_labels = None
depends_on = None

_LOCK_TIMEOUT = "5s"
_DROP_ATTEMPTS = 12
_RETRY_DELAY_S = 5
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"


def _is_lock_timeout(error: DBAPIError) -> bool:
    # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on the
    # driver error, but the DBAPI error type does not declare it.
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _drop_table_with_bounded_lock_wait(table_name: str) -> None:
    """Drops a table whose foreign key points at `document`.

    The drop needs an ACCESS EXCLUSIVE lock on `document`. While it waits for
    that lock, every other query on `document` queues behind it. A short
    lock_timeout keeps that stall short when a long transaction (for example
    an indexing batch) holds a lock on `document`. Each attempt runs in a
    savepoint, so a timeout does not abort the migration transaction.
    """
    bind = op.get_bind()
    for attempt in range(1, _DROP_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                op.drop_table(table_name)
            break
        except DBAPIError as e:
            # Only a lock timeout is worth a retry. Raise other errors at once.
            if attempt == _DROP_ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "Could not lock `document` to drop %s (attempt %s/%s). Retrying in %ss.",
                table_name,
                attempt,
                _DROP_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def upgrade() -> None:
    op.drop_table("opensearch_tenant_migration_record")
    _drop_table_with_bounded_lock_wait("opensearch_document_migration_record")


def downgrade() -> None:
    op.create_table(
        "opensearch_document_migration_record",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("document_id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_opensearch_document_migration_record_status",
        "opensearch_document_migration_record",
        ["status"],
    )
    op.create_index(
        "ix_opensearch_document_migration_record_attempts_count",
        "opensearch_document_migration_record",
        ["attempts_count"],
    )
    op.create_index(
        "ix_opensearch_document_migration_record_created_at",
        "opensearch_document_migration_record",
        ["created_at"],
    )

    op.create_table(
        "opensearch_tenant_migration_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "document_migration_record_table_population_status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "num_times_observed_no_additional_docs_to_populate_migration_table",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "overall_document_migration_status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "num_times_observed_no_additional_docs_to_migrate",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("vespa_visit_continuation_token", sa.Text(), nullable=True),
        sa.Column(
            "total_chunks_migrated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("migration_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enable_opensearch_retrieval",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "total_chunks_errored", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_chunks_in_vespa", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("approx_chunk_count_in_vespa", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX idx_opensearch_tenant_migration_singleton "
            "ON opensearch_tenant_migration_record ((true))"
        )
    )
