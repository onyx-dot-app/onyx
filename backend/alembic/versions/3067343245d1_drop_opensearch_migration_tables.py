"""drop opensearch migration tables

These tables tracked the Vespa to OpenSearch migration. Every instance has
finished that migration, and nothing reads or writes the tables anymore.

Revision ID: 3067343245d1
Revises: b7c2e4f1a9d3
Create Date: 2026-09-30 13:47:48.331663

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3067343245d1"
down_revision = "b7c2e4f1a9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("opensearch_tenant_migration_record")
    op.drop_table("opensearch_document_migration_record")


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
