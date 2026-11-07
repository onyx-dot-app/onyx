"""widen capability report source column

The source column is a non-native enum without values_callable, so rows hold
member names (VARCHAR sized to the longest name). JIRA_SERVICE_MANAGEMENT is
longer than the names that sized it.

Revision ID: a8c4e1b9d203
Revises: c3e8a1f5d702
Create Date: 2026-11-07 12:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a8c4e1b9d203"
down_revision = "c3e8a1f5d702"
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
    connection: sa.Connection = op.get_bind()
    has_jira_service_management_rows: bool = connection.execute(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {_TABLE} "
            f"WHERE {_COLUMN} = 'JIRA_SERVICE_MANAGEMENT')"
        )
    ).scalar_one()
    if has_jira_service_management_rows:
        raise RuntimeError(
            "Cannot downgrade while JIRA_SERVICE_MANAGEMENT capability reports exist"
        )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
