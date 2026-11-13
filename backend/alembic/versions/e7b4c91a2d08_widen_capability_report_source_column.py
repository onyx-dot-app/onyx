"""widen capability report source column

The source column is a non-native enum without values_callable, so rows hold
member names (VARCHAR sized to the longest name when the table was created).
JIRA_SERVICE_MANAGEMENT is longer than GOOGLE_CLOUD_STORAGE, which sized it.

Other DocumentSource columns already fit the new name: connector.source,
tag.source, and search_doc.source_type are VARCHAR(50); credential.source is
VARCHAR(100); hierarchy_node.source and connector_event_inbox.source have no
length limit.

Revision ID: e7b4c91a2d08
Revises: fdaeeca238a1
Create Date: 2026-11-11 01:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e7b4c91a2d08"
down_revision = "fdaeeca238a1"
branch_labels = None
depends_on = None

_TABLE = "credential_capability_report"
_COLUMN = "source"
# len("JIRA_SERVICE_MANAGEMENT")
_NEW_LENGTH = 25
# len("GOOGLE_CLOUD_STORAGE"), the longest name when the table was created.
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
    # The older code does not know this source. Drop those reports so the
    # column can return to the previous width. Other rows stay.
    op.execute(
        sa.text(
            f"DELETE FROM {_TABLE} WHERE {_COLUMN} IN "
            "('JIRA_SERVICE_MANAGEMENT', 'jira_service_management')"
        )
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
