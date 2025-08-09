"""add_sync_warnings_to_sync_record

Revision ID: 9ee7f8d9787d
Revises: 3fc5d75723b3
Create Date: 2025-07-30 19:11:54.452420

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9ee7f8d9787d"
down_revision = "3fc5d75723b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sync_warnings column to store validation warnings from connector perm sync
    op.add_column(
        "sync_record",
        sa.Column("sync_warnings", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # Drop the sync_warnings column
    op.drop_column("sync_record", "sync_warnings")
