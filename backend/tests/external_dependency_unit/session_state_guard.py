"""Find Postgres session settings that a test left on the app's pooled connections.

A plain `SET` (or `set_config(..., false)`) that commits, or runs on an AUTOCOMMIT
connection, stays on the connection after the pool takes it back. The next test
that checks the connection out then runs with that setting: for example a
`lock_timeout` of 100ms makes a blocking insert fail at once.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import QueuePool

from onyx.db.engine.sql_engine import SqlEngine

# SQLAlchemy sets this itself when it restores the isolation level of a
# connection that a caller switched to AUTOCOMMIT.
_SET_BY_SQLALCHEMY = frozenset({"transaction_isolation"})

_SESSION_SETTINGS = text(
    "SELECT name, setting FROM pg_settings WHERE source = 'session' ORDER BY name"
)


def _app_engines() -> list[Engine]:
    engines: list[Engine] = []
    for get_engine in (SqlEngine.get_engine, SqlEngine.get_readonly_engine):
        try:
            engines.append(get_engine())
        except RuntimeError:
            # Not initialized in this process.
            continue
    return engines


def reset_leaked_session_settings() -> list[str]:
    """Check out every idle pooled connection of the app engines, reset any
    session settings left on it, and return a description of each one found."""
    leaks: list[str] = []
    for engine in _app_engines():
        pool = engine.pool
        if not isinstance(pool, QueuePool):
            continue
        # Holding them all at once makes the pool hand out each idle one.
        connections: list[Connection] = []
        try:
            connections.extend(engine.connect() for _ in range(pool.checkedin()))
            for connection in connections:
                found = [
                    f"{name}={setting}"
                    for name, setting in connection.execute(_SESSION_SETTINGS).all()
                    if name not in _SET_BY_SQLALCHEMY
                ]
                if found:
                    leaks.append(", ".join(found))
                    connection.exec_driver_sql("RESET ALL")
                    connection.commit()
                else:
                    connection.rollback()
        finally:
            for connection in connections:
                connection.close()
    return leaks
