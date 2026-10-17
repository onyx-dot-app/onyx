"""widen search_settings reclaim_status

Migration b3f1c9a27d84 sized reclaim_status (a non-native enum, so VARCHAR) to
the longest IndexReclaimStatus member when it ran. Databases that ran it before
RECLAIMED was added got VARCHAR(8), so writes of RECLAIMED (9 characters) fail.
This sets one explicit length on all databases.

Revision ID: 8e870f2a7a29
Revises: 38720c9e7f8f
Create Date: 2026-10-01 17:27:34.452828

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8e870f2a7a29"
down_revision = "38720c9e7f8f"
branch_labels = None
depends_on = None

# Must match the `length` of SearchSettings.reclaim_status in models.py.
_RECLAIM_STATUS_LENGTH = 16
# The length a fresh install got before this migration (RECLAIMED). A downgrade
# to 8 would bring back the bug and fail on rows that are already RECLAIMED.
_PREVIOUS_RECLAIM_STATUS_LENGTH = 9


def upgrade() -> None:
    op.alter_column(
        "search_settings",
        "reclaim_status",
        existing_type=sa.String(),
        type_=sa.String(length=_RECLAIM_STATUS_LENGTH),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "search_settings",
        "reclaim_status",
        existing_type=sa.String(length=_RECLAIM_STATUS_LENGTH),
        type_=sa.String(length=_PREVIOUS_RECLAIM_STATUS_LENGTH),
        existing_nullable=True,
    )
