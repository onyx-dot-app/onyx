"""allow a disconnected integration connection

A user who disconnects from a custom app whose old organization values would
connect them again keeps a row with the status `disconnected`.

Revision ID: c50ffc79d188
Revises: 7a3c9e5b1d08
Create Date: 2026-11-20 00:26:10.230427

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c50ffc79d188"
down_revision = "7a3c9e5b1d08"
branch_labels = None
depends_on = None

_TABLE = "integration_connection"
_CONSTRAINT = "ck_integration_connection_status"
LOCK_TIMEOUT = "60s"


def _replace_status_check(statuses: tuple[str, ...]) -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    op.create_check_constraint(
        _CONSTRAINT, _TABLE, f"status IN ({values})", postgresql_not_valid=True
    )
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        try:
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.{_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}"
            )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def upgrade() -> None:
    _replace_status_check(("connected", "needs_reconnect", "disconnected"))


def downgrade() -> None:
    op.execute(f"DELETE FROM {_TABLE} WHERE status = 'disconnected'")
    _replace_status_check(("connected", "needs_reconnect"))
