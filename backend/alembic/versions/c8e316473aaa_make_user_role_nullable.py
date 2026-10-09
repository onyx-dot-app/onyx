"""make user role nullable

The ``user.role`` column is no longer written or read by application
code — admin status is derived from group membership and classification
lives on ``user.account_type``. Relax the NOT NULL constraint so inserts
that omit the column (which is now the default path after the write-path
cleanup) succeed. The column itself is kept as a tombstone for rollback
safety and will be dropped in a follow-up migration once the new model
has been in production for a release cycle.

Revision ID: c8e316473aaa
Revises: f8048443da9e
Create Date: 2026-04-14 14:57:29.520645

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision = "c8e316473aaa"
down_revision = "f8048443da9e"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "user",
        "role",
        existing_type=sa.VARCHAR(length=14),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill NULLs written while the column was optional; otherwise
    # restoring NOT NULL fails against rows inserted after the upgrade.
    op.execute("UPDATE \"user\" SET role = 'BASIC' WHERE role IS NULL")
    op.alter_column(
        "user",
        "role",
        existing_type=sa.VARCHAR(length=14),
        nullable=False,
    )
