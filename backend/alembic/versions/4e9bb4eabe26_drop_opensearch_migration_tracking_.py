"""drop opensearch migration tracking tables

Revision ID: 4e9bb4eabe26
Revises: 7f5b159041be
Create Date: 2026-05-23 12:22:43.602119

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4e9bb4eabe26"
down_revision = "7f5b159041be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # drop_table removes the table along with its indexes and constraints.
    op.drop_table("opensearch_document_migration_record")
    op.drop_table("opensearch_tenant_migration_record")


def downgrade() -> None:
    # Recreate opensearch_document_migration_record in its final-state schema
    # (the single create migration covered every column on this table).
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

    # Recreate opensearch_tenant_migration_record with the full set of
    # columns from all four historical migrations
    # (cbc03e08d0f3 + feead2911109 + 93c15d6a6fbb + 631fd2504136).
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
            "total_chunks_migrated",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_chunks_errored",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_chunks_in_vespa",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("migration_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enable_opensearch_retrieval",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("approx_chunk_count_in_vespa", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX idx_opensearch_tenant_migration_singleton
            ON opensearch_tenant_migration_record ((true))
            """
        )
    )
