"""widen capability report source column

The source column is a non-native enum without values_callable, so rows hold
member names (VARCHAR sized to the longest name). JIRA_SERVICE_MANAGEMENT is
longer than the names that sized it.

Revision ID: a1c9e4f27b03
Revises: 70aed6c27639
Create Date: 2026-11-05 00:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1c9e4f27b03"
down_revision = "70aed6c27639"
branch_labels = None
depends_on = None

_TABLE = "credential_capability_report"
_COLUMN = "source"
# Matches the String(50) used for source columns elsewhere (e50154680a5c).
_NEW_LENGTH = 50
# len("GOOGLE_CLOUD_STORAGE"), the longest name before this revision.
_OLD_LENGTH = 20


def upgrade() -> None:
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_NEW_LENGTH),
        existing_type=sa.String(length=_OLD_LENGTH),
        existing_nullable=False,
    )


def downgrade() -> None:
    # The older code does not know the new source; capability reports are
    # regenerable, so drop rows the old column cannot hold.
    op.execute(
        sa.text(
            f"DELETE FROM {_TABLE} WHERE {_COLUMN} = 'JIRA_SERVICE_MANAGEMENT'"
        )
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
