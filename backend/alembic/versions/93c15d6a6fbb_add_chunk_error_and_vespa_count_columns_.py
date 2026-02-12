"""add chunk error and vespa count columns to opensearch tenant migration

Revision ID: 93c15d6a6fbb
Revises: d3fd499c829c
Create Date: 2026-02-11 23:07:34.576725

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "93c15d6a6fbb"
down_revision = "d3fd499c829c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "total_chunks_errored",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "total_chunks_in_vespa",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("opensearch_tenant_migration_record", "total_chunks_in_vespa")
    op.drop_column("opensearch_tenant_migration_record", "total_chunks_errored")
