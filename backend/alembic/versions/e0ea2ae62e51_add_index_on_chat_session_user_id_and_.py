"""add index on chat_session user_id and time_updated

Revision ID: e0ea2ae62e51
Revises: c2cc933f0a40
Create Date: 2026-07-23 23:13:21.795575

Adds a composite btree index on (user_id, onyxbot_flow, time_updated DESC) to
back the chat-history sidebar query (get_chat_sessions_by_user), which filters
on user_id + onyxbot_flow and orders by time_updated DESC. Without it Postgres
plans a Seq Scan + Sort that degrades linearly as chat_session grows.

chat_session is hot (time_updated is bumped on every message), so the index is
built CONCURRENTLY. That cannot run inside a transaction, and
op.get_context().autocommit_block() is unusable with this project's env.py:
the async connection autobegins a transaction when env.py sets search_path, so
alembic treats the transaction as externally managed and asserts. Instead we
commit the migration connection's transaction (also required so CONCURRENTLY
doesn't wait forever on our own snapshot) and run the DDL on a dedicated
AUTOCOMMIT connection. A fresh connection does not inherit the migration
connection's per-tenant search_path, so all statements schema-qualify using
current_schema() read from the migration connection.
"""

import logging
import time

import asyncpg.exceptions
import psycopg2.errors
from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError


# revision identifiers, used by Alembic.
revision = "e0ea2ae62e51"
down_revision = "c2cc933f0a40"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

INDEX_NAME = "ix_chat_session_user_id_onyxbot_flow_time_updated"

# CONCURRENTLY waits on every older transaction in the database, whatever schema
# it runs in. A bounded wait fails naming the schema instead of hanging the run.
LOCK_TIMEOUT = "60s"
MAX_BUILD_ATTEMPTS = 10
RETRY_DELAY_SEC = 5


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index doesn't exist, otherwise pg_index.indisvalid.

    A failed CREATE INDEX CONCURRENTLY leaves an INVALID index behind, which
    IF NOT EXISTS / a plain existence check would mistake for a finished build.
    """
    row = conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": f'"{schema}"."{INDEX_NAME}"'},
    ).one_or_none()
    return row[0] if row is not None else None


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    """Commit the migration txn and return (bind, current tenant schema)."""
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # env.py's plain SET search_path is session-level and survives this
    # commit; alembic's version-table update autobegins a new transaction
    # afterwards, which env.py commits at the end of the schema's run.
    bind.commit()
    return bind, schema


def _is_lock_timeout(e: DBAPIError) -> bool:
    # Deployed runs use asyncpg, whose SQLAlchemy adapter raises its own error
    # from the driver's. Migration tests run on a sync psycopg2 engine.
    cause: BaseException | None = e.orig.__cause__ if e.orig is not None else None
    return isinstance(cause, asyncpg.exceptions.LockNotAvailableError) or isinstance(
        e.orig, psycopg2.errors.LockNotAvailable
    )


def _build_index(conn: sa.engine.Connection, schema: str) -> None:
    """Builds the index, retrying each time another transaction outlasts lock_timeout.

    A timed-out CONCURRENTLY build leaves an INVALID index, so every attempt
    drops that leftover first."""
    conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    for attempt in range(1, MAX_BUILD_ATTEMPTS + 1):
        try:
            if _index_state(conn, schema) is False:
                conn.exec_driver_sql(
                    f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"'
                )
            conn.exec_driver_sql(
                f'CREATE INDEX CONCURRENTLY "{INDEX_NAME}" '
                f'ON "{schema}".chat_session (user_id, onyxbot_flow, time_updated DESC)'
            )
            return
        except DBAPIError as e:
            if not _is_lock_timeout(e):
                raise
            if attempt == MAX_BUILD_ATTEMPTS:
                raise RuntimeError(
                    f"{INDEX_NAME} on {schema}: another transaction blocked the "
                    f"build for {MAX_BUILD_ATTEMPTS} attempts of {LOCK_TIMEOUT}. "
                    "End that transaction and rerun the migration"
                ) from e
            logger.warning(
                "%s on %s: build blocked by another transaction, attempt %d/%d",
                INDEX_NAME,
                schema,
                attempt,
                MAX_BUILD_ATTEMPTS,
            )
            time.sleep(RETRY_DELAY_SEC)


def upgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is True:
            return
        _build_index(conn, schema)


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
