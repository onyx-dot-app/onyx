"""Add Total Docs for Index Attempt

Revision ID: d61e513bef0a
Revises: 46625e4745d4
Create Date: 2023-10-27 23:02:43.369964

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d61e513bef0a"
down_revision = "46625e4745d4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column("new_docs_indexed", sa.Integer(), nullable=True),
    )
    op.alter_column(
        "index_attempt", "num_docs_indexed", new_column_name="total_docs_indexed"
    )


def downgrade() -> None:
    op.alter_column(
        "index_attempt", "total_docs_indexed", new_column_name="num_docs_indexed"
    )
    op.drop_column("index_attempt", "new_docs_indexed")
