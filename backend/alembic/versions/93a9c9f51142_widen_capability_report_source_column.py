"""widen credential_capability_report.source

The source column is a non-native enum, so it is a VARCHAR sized to the longest
DocumentSource member when the table was created. df90f43d9ab2 ran before
JIRA_SERVICE_MANAGEMENT existed and created VARCHAR(20); that name is 23
characters. Upgraded databases therefore reject JSM capability report writes
until the column is widened. Fresh installs already get VARCHAR(23).

Revision ID: 93a9c9f51142
Revises: b7d2e4f1a9c3
Create Date: 2026-10-30 07:22:24.902541

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "93a9c9f51142"
down_revision = "b7d2e4f1a9c3"
branch_labels = None
depends_on = None

_TABLE = "credential_capability_report"
_COLUMN = "source"
# len("JIRA_SERVICE_MANAGEMENT")
_NEW_LENGTH = 23
# The length df90f43d9ab2 created before JSM was added.
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
    # The previous release cannot read a JSM capability report. These rows are
    # disposable latest-only check results; drop them rather than mislabeling
    # them as another source before restoring the old width.
    op.execute(
        sa.text(f"DELETE FROM {_TABLE} WHERE {_COLUMN} = 'JIRA_SERVICE_MANAGEMENT'")
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
