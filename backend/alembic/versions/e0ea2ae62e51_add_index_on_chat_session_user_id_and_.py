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

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e0ea2ae62e51"
down_revision = "c2cc933f0a40"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chat_session_user_id_onyxbot_flow_time_updated"


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


def upgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        state = _index_state(conn, schema)
        if state is True:
            return
        if state is False:
            conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY "{INDEX_NAME}" '
            f'ON "{schema}".chat_session (user_id, onyxbot_flow, time_updated DESC)'
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
