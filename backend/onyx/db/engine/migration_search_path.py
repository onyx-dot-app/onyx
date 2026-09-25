"""Keep a migration connection's search_path pinned to its tenant schema.

Tenant migrations connect through pgbouncer in transaction pooling mode. There
the server connection is only pinned for one transaction, so a session-level
`SET search_path` lasts until the first commit, and a migration that commits
mid-run (index builds run CONCURRENTLY) leaves the next transaction on a server
connection with the default search_path. Re-issuing the SET as the first
statement of every transaction makes the schema follow the transaction,
whatever the pooler does between them.
"""

from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.engine import Connection

# `Connection.info` key holding the schema this connection migrates.
SEARCH_PATH_SCHEMA_INFO_KEY = "onyx_migration_search_path_schema"
# Set when a transaction begins on a pinned connection, cleared by the SET.
_REAPPLY_PENDING_INFO_KEY = "onyx_migration_search_path_pending"


def pin_search_path_to_schema(connection: Connection, schema_name: str) -> None:
    """Set the schema now and record it for the engine's re-apply listeners."""
    # Schema names come from the tenant registry or the migration CLI, never
    # from end users. The marker is set after the SET so the listeners only
    # re-issue it for the transactions that follow.
    connection.exec_driver_sql(f'SET search_path TO "{schema_name}"')
    connection.info[SEARCH_PATH_SCHEMA_INFO_KEY] = schema_name


def install_search_path_reapply(sync_engine: Engine) -> None:
    """Re-issue `SET search_path` before the first statement of each transaction."""
    event.listen(sync_engine, "begin", _flag_reapply)
    event.listen(sync_engine, "before_cursor_execute", _reapply_before_statement)


def _flag_reapply(connection: Connection) -> None:
    if SEARCH_PATH_SCHEMA_INFO_KEY in connection.info:
        connection.info[_REAPPLY_PENDING_INFO_KEY] = True


def _reapply_before_statement(
    connection: Connection,
    cursor: Any,
    _statement: str,
    _parameters: Any,
    _context: Any,
    _executemany: bool,
) -> None:
    if not connection.info.pop(_REAPPLY_PENDING_INFO_KEY, False):
        return
    schema_name = connection.info[SEARCH_PATH_SCHEMA_INFO_KEY]
    # The raw cursor keeps this out of SQLAlchemy's transaction bookkeeping.
    # The transaction has already begun, so the SET lands on the same server
    # connection as the statement that follows.
    cursor.execute(f'SET search_path TO "{schema_name}"')
