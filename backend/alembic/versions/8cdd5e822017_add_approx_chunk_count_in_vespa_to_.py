"""add approx_chunk_count_in_vespa to opensearch tenant migration

Revision ID: 8cdd5e822017
Revises: 19c0ccb01687
Create Date: 2026-02-18 18:41:40.452149

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8cdd5e822017"
down_revision = "19c0ccb01687"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "opensearch_tenant_migration_record",
        sa.Column(
            "approx_chunk_count_in_vespa",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("opensearch_tenant_migration_record", "approx_chunk_count_in_vespa")
