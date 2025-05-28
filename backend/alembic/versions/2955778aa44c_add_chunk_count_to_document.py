"""add chunk count to document

Revision ID: 2955778aa44c
Revises: c0aab6edb6dd
Create Date: 2025-01-04 11:39:43.268612

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2955778aa44c"
down_revision = "c0aab6edb6dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document", sa.Column("chunk_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document", "chunk_count")
