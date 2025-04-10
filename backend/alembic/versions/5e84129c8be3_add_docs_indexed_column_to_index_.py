"""Add docs_indexed_column + time_started to index_attempt table

Revision ID: 5e84129c8be3
Revises: e6a4bbc13fe4
Create Date: 2023-08-10 21:43:09.069523

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e84129c8be3"
down_revision = "e6a4bbc13fe4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column("num_docs_indexed", sa.Integer()),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "time_started",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "time_started")
    op.drop_column("index_attempt", "num_docs_indexed")
