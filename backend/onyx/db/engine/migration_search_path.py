"""Keeps an Alembic migration connection on its tenant schema across commits.

A migration that commits mid-run (to build an index CONCURRENTLY) starts a new
transaction on the same connection. Through PgBouncer transaction pooling that
transaction can run on another server connection, which does not carry the
session-level search_path. SET LOCAL as the first statement of every
transaction pins the tenant schema whichever server connection runs it, and
leaves no search_path behind on the pooled server connection.
"""

from sqlalchemy import event
from sqlalchemy.engine import Connection


def pin_search_path_per_transaction(connection: Connection, schema_name: str) -> None:
    """Set a transaction-local search_path to ``schema_name`` in the open
    transaction, if any, and at the start of every later one on ``connection``."""
    quoted_schema_name = connection.dialect.identifier_preparer.quote(schema_name)
    set_search_path = f"SET LOCAL search_path TO {quoted_schema_name}"

    # Runs before the DBAPI begins, so the SET is the transaction's first
    # statement; SQLAlchemy does not autobegin again inside this hook.
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql(set_search_path)

    event.listen(connection, "begin", _on_begin)
    if connection.in_transaction():
        connection.exec_driver_sql(set_search_path)
