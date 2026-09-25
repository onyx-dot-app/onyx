"""rebuild chat_message chat_session_id index where missing

Revision ID: da94f38390a5
Revises: ac05f4a21dbd
Create Date: 2026-09-25 13:39:45.369786

f57f35403f6c built ix_chat_message_chat_session_id, but through a
transaction-pooled pgbouncer connection its `current_schema()` read could land
on a server connection without the tenant search_path, so the build ran against
another schema and the tenant it migrated ended up without the index. This
revision repeats the build for every schema that still lacks it. Schemas that
have a valid index skip in one catalog read.

Same shape as f57f35403f6c: commit the migration transaction, then build
CONCURRENTLY on a dedicated AUTOCOMMIT connection, schema-qualifying every
statement with the schema read from the migration connection.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "da94f38390a5"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chat_message_chat_session_id"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index doesn't exist, otherwise pg_index.indisvalid."""
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
            f'ON "{schema}".chat_message (chat_session_id)'
        )


def downgrade() -> None:
    # The index belongs to f57f35403f6c; this revision only repairs it.
    pass
