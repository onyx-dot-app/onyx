"""allow a disconnected integration connection

A user who disconnects from a custom app whose old organization values would
connect them again keeps a row with the status `disconnected`.

Revision ID: c50ffc79d188
Revises: 7a3c9e5b1d08
Create Date: 2026-11-20 00:26:10.230427

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c50ffc79d188"
down_revision = "7a3c9e5b1d08"
branch_labels = None
depends_on = None

_TABLE = "integration_connection"
_CONSTRAINT = "ck_integration_connection_status"


def _replace_status_check(statuses: tuple[str, ...]) -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    # Each existing row passes the new rule, so no scan is necessary.
    op.create_check_constraint(
        _CONSTRAINT, _TABLE, f"status IN ({values})", postgresql_not_valid=True
    )


def upgrade() -> None:
    _replace_status_check(("connected", "needs_reconnect", "disconnected"))


def downgrade() -> None:
    op.execute(f"DELETE FROM {_TABLE} WHERE status = 'disconnected'")
    _replace_status_check(("connected", "needs_reconnect"))
