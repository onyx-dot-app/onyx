"""add removed documents to index_attempt

Revision ID: 5f4b8568a221
Revises: dbaa756c2ccf
Create Date: 2024-02-16 15:02:03.319907

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5f4b8568a221"
down_revision = "8987770549c0"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column("docs_removed_from_index", sa.Integer()),
    )
    op.execute("UPDATE index_attempt SET docs_removed_from_index = 0")


def downgrade() -> None:
    op.drop_column("index_attempt", "docs_removed_from_index")
