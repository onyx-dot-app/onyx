"""add_indexing_start_to_connector

Revision ID: 08a1eda20fe1
Revises: 8a87bd6ec550
Create Date: 2024-07-23 11:12:39.462397

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "08a1eda20fe1"
down_revision = "8a87bd6ec550"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "connector", sa.Column("indexing_start", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("connector", "indexing_start")
