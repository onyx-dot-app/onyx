"""widen search_settings reclaim_status

Migration b3f1c9a27d84 sized reclaim_status (a non-native enum, so VARCHAR) to
the longest IndexReclaimStatus member when it ran. Databases that ran it before
RECLAIMED was added got VARCHAR(8), which "RECLAIMED" (9 characters) does not fit,
and fresh installs got VARCHAR(9). Releases without this migration write RECLAIMED
as "RECLAIMD" on every database. This sets one length on all databases and rewrites
those rows to "RECLAIMED", which every release reads.

Revision ID: ca7cc9a98a6b
Revises: d7f46adc4d49
Create Date: 2026-10-26 14:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ca7cc9a98a6b"
down_revision = "d7f46adc4d49"
branch_labels = None
depends_on = None

_RECLAIM_STATUS_LENGTH = 64
# The length a fresh install got before this migration (RECLAIMED). A downgrade
# to 8 would fail on rows that hold "RECLAIMED".
_PREVIOUS_RECLAIM_STATUS_LENGTH = 9


def upgrade() -> None:
    op.alter_column(
        "search_settings",
        "reclaim_status",
        existing_type=sa.String(),
        type_=sa.String(length=_RECLAIM_STATUS_LENGTH),
        existing_nullable=True,
    )
    op.execute(
        "UPDATE search_settings SET reclaim_status = 'RECLAIMED' "
        "WHERE reclaim_status = 'RECLAIMD'"
    )


def downgrade() -> None:
    # Every stored value fits VARCHAR(9), and every release with RECLAIMED reads
    # "RECLAIMED".
    op.alter_column(
        "search_settings",
        "reclaim_status",
        existing_type=sa.String(length=_RECLAIM_STATUS_LENGTH),
        type_=sa.String(length=_PREVIOUS_RECLAIM_STATUS_LENGTH),
        existing_nullable=True,
    )
