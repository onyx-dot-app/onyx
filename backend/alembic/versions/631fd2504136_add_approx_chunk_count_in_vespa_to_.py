"""add approx_chunk_count_in_vespa to opensearch tenant migration

Revision ID: 631fd2504136
Revises: c7f2e1b4a9d3
Create Date: 2026-02-18 21:07:52.831215

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "631fd2504136"
down_revision = "c7f2e1b4a9d3"
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
