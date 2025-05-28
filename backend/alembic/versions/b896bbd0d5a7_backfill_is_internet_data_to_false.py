"""backfill is_internet data to False

Revision ID: b896bbd0d5a7
Revises: 44f856ae2a4a
Create Date: 2024-07-16 15:21:05.718571

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b896bbd0d5a7"
down_revision = "44f856ae2a4a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("UPDATE search_doc SET is_internet = FALSE WHERE is_internet IS NULL")


def downgrade() -> None:
    pass
