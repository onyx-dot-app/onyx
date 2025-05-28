"""add pinned assistants

Revision ID: aeda5f2df4f6
Revises: c5eae4a75a1b
Create Date: 2025-01-09 16:04:10.770636

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "aeda5f2df4f6"
down_revision = "c5eae4a75a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("pinned_assistants", postgresql.JSONB(), nullable=True)
    )
    op.execute('UPDATE "user" SET pinned_assistants = chosen_assistants')


def downgrade() -> None:
    op.drop_column("user", "pinned_assistants")
