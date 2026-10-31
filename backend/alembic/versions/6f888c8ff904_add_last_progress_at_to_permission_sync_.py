"""add last_progress_at to permission sync attempts

Revision ID: 6f888c8ff904
Revises: aac91dfef2c7
Create Date: 2026-10-13 13:16:48.492835

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f888c8ff904"
down_revision = "aac91dfef2c7"
branch_labels = None
depends_on = None

_TABLES = ("doc_permission_sync_attempt", "external_group_permission_sync_attempt")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "last_progress_at")
