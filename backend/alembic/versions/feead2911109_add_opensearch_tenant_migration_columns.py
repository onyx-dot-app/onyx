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
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column("vespa_visit_continuation_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "total_chunks_migrated",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "migration_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "enable_opensearch_retrieval",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("opensearch_tenant_migration_record", "enable_opensearch_retrieval")
    op.drop_column("opensearch_tenant_migration_record", "migration_completed_at")
    op.drop_column("opensearch_tenant_migration_record", "created_at")
    op.drop_column("opensearch_tenant_migration_record", "total_chunks_migrated")
    op.drop_column(
        "opensearch_tenant_migration_record", "vespa_visit_continuation_token"
    )
