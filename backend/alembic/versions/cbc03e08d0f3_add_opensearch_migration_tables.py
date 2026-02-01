"""add_opensearch_migration_tables

Revision ID: cbc03e08d0f3
Revises: be87a654d5af
Create Date: 2026-01-31 17:00:45.176604

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cbc03e08d0f3"
down_revision = "be87a654d5af"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create opensearch_document_migration_record table.
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
    # 2. Create indices.
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

    # 3. Create opensearch_tenant_migration_record table (singleton).
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
        sa.PrimaryKeyConstraint("id"),
    )

    # 4. Create unique index on constant to enforce singleton pattern.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX idx_opensearch_tenant_migration_singleton
            ON opensearch_tenant_migration_record ((true))
            """
        )
    )


def downgrade() -> None:
    # Drop opensearch_tenant_migration_record.
    op.drop_index(
        "idx_opensearch_tenant_migration_singleton",
        table_name="opensearch_tenant_migration_record",
    )
    op.drop_table("opensearch_tenant_migration_record")

    # Drop opensearch_document_migration_record.
    op.drop_index(
        "ix_opensearch_document_migration_record_created_at",
        table_name="opensearch_document_migration_record",
    )
    op.drop_index(
        "ix_opensearch_document_migration_record_attempts_count",
        table_name="opensearch_document_migration_record",
    )
    op.drop_index(
        "ix_opensearch_document_migration_record_status",
        table_name="opensearch_document_migration_record",
    )
    op.drop_table("opensearch_document_migration_record")
