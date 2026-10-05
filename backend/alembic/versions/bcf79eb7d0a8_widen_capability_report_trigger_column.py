"""widen capability report trigger column

The trigger column is a non-native enum (VARCHAR sized to the longest value).
"connector_config_update" is longer than the values that sized it.

Revision ID: bcf79eb7d0a8
Revises: 14846d586881
Create Date: 2026-10-05 16:54:08.907556

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "bcf79eb7d0a8"
down_revision = "14846d586881"
branch_labels = None
depends_on = None

_TABLE = "credential_capability_report"
_COLUMN = "trigger"
# len("connector_config_update")
_NEW_LENGTH = 23
# len("credential_created"), the longest value before this revision.
_OLD_LENGTH = 18


def upgrade() -> None:
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_NEW_LENGTH),
        existing_type=sa.String(length=_OLD_LENGTH),
        existing_nullable=False,
    )


def downgrade() -> None:
    # The older code does not know the new trigger; an edit's validation is
    # closest to a pairing validation.
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_COLUMN} = 'cc_pair_validation' "
            f"WHERE {_COLUMN} = 'connector_config_update'"
        )
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
