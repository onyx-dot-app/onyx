"""Add Above Below to Persona

Revision ID: 2d2304e27d8c
Revises: 4b08d97e175a
Create Date: 2024-08-21 19:15:15.762948

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2d2304e27d8c"
down_revision = "4b08d97e175a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("persona", sa.Column("chunks_above", sa.Integer(), nullable=True))
    op.add_column("persona", sa.Column("chunks_below", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE persona SET chunks_above = 1, chunks_below = 1 WHERE chunks_above IS NULL AND chunks_below IS NULL"
    )

    op.alter_column("persona", "chunks_above", nullable=False)
    op.alter_column("persona", "chunks_below", nullable=False)


def downgrade() -> None:
    op.drop_column("persona", "chunks_below")
    op.drop_column("persona", "chunks_above")
