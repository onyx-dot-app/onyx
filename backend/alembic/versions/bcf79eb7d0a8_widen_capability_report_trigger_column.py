"""widen capability report trigger column

The trigger column is a non-native enum without values_callable, so rows hold
member names (VARCHAR sized to the longest name). CONNECTOR_CONFIG_UPDATE is
longer than the names that sized it.

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
# len("CONNECTOR_CONFIG_UPDATE")
_NEW_LENGTH = 23
# len("CREDENTIAL_CREATED"), the longest name before this revision.
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
            f"UPDATE {_TABLE} SET {_COLUMN} = 'CC_PAIR_VALIDATION' "
            f"WHERE {_COLUMN} = 'CONNECTOR_CONFIG_UPDATE'"
        )
    )
    op.alter_column(
        _TABLE,
        _COLUMN,
        type_=sa.String(length=_OLD_LENGTH),
        existing_type=sa.String(length=_NEW_LENGTH),
        existing_nullable=False,
    )
