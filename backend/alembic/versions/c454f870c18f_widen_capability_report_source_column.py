"""widen capability report source column

The source column is a non-native enum without values_callable, so rows hold
member names (VARCHAR sized to the longest name). JIRA_SERVICE_MANAGEMENT is
longer than the names that sized it.

Revision ID: c454f870c18f
Revises: 414dfccc5e24
Create Date: 2026-11-15 04:26:07.%f

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c454f870c18f"
down_revision = "414dfccc5e24"
branch_labels = None
depends_on = None

_TABLE = "credential_capability_report"
_COLUMN = "source"
# len("JIRA_SERVICE_MANAGEMENT")
_NEW_LENGTH = 23
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
    # The older code does not know the new source; JSM issues are Jira issues.
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_COLUMN} = 'JIRA' "
            f"WHERE {_COLUMN} = 'JIRA_SERVICE_MANAGEMENT'"
        )
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
