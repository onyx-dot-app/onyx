"""add_opensearch_migration_tables

Revision ID: d31d10d9b681
Revises: e7f8a9b0c1d2
Create Date: 2026-01-30 09:16:46.467456

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d31d10d9b681"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opensearch_tenant_migration_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "document_migration_record_table_population_status",
            sa.Enum(
                "pending",
                "completed",
                name="opensearchtenantmigrationstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "num_times_observed_no_additional_docs_to_populate_migration_table",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "overall_document_migration_status",
            sa.Enum(
                "pending",
                "completed",
                name="opensearchtenantmigrationstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "num_times_observed_no_additional_docs_to_migrate",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_opensearch_tenant_migration_singleton",
        "opensearch_tenant_migration_record",
        [sa.text("(true)")],
        unique=True,
    )
    op.create_table(
        "opensearch_document_migration_record",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "completed",
                "failed",
                "permanently_failed",
                name="opensearchdocumentmigrationstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(
        op.f("ix_opensearch_document_migration_record_status"),
        "opensearch_document_migration_record",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_opensearch_document_migration_record_status"),
        table_name="opensearch_document_migration_record",
    )
    op.drop_table("opensearch_document_migration_record")
    op.drop_index(
        "idx_opensearch_tenant_migration_singleton",
        table_name="opensearch_tenant_migration_record",
    )
    op.drop_table("opensearch_tenant_migration_record")
