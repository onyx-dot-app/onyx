"""rebuild chat_message chat_session_id index where missing

Revision ID: da94f38390a5
Revises: ac05f4a21dbd
Create Date: 2026-09-25 13:39:45.369786

f57f35403f6c built ix_chat_message_chat_session_id, but through a
transaction-pooled pgbouncer connection its `current_schema()` read could land
on a server connection without the tenant search_path, so the existence check
and build targeted another schema and the tenant it migrated ended up without
the index. This revision repeats the build for every schema that still lacks
it. Schemas that have a valid index skip in one catalog read.

CONCURRENTLY cannot run inside a transaction, so the migration transaction is
committed and the build runs on a dedicated AUTOCOMMIT connection. The schema
comes from the tenant contextvar env.py sets, not from the connection.
"""

from alembic import op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import sqlalchemy as sa

from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


# revision identifiers, used by Alembic.
revision = "da94f38390a5"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None

TABLE_NAME = "chat_message"
COLUMN_NAME = "chat_session_id"
INDEX_NAME = "ix_chat_message_chat_session_id"

_pg_index = sa.table("pg_index", sa.column("indexrelid"), sa.column("indisvalid"))


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index doesn't exist, otherwise pg_index.indisvalid."""
    qualified_name = f'"{schema}"."{INDEX_NAME}"'
    return conn.execute(
        sa.select(_pg_index.c.indisvalid).where(
            _pg_index.c.indexrelid == sa.func.to_regclass(qualified_name)
        )
    ).scalar_one_or_none()


def repair_index(conn: sa.engine.Connection, schema: str) -> None:
    """Leave the schema with a valid index. ``conn`` must be in AUTOCOMMIT mode,
    since CONCURRENTLY cannot run inside a transaction."""
    state = _index_state(conn, schema)
    if state is True:
        return
    operations = Operations(MigrationContext.configure(conn))
    if state is False:
        operations.drop_index(
            INDEX_NAME,
            table_name=TABLE_NAME,
            schema=schema,
            postgresql_concurrently=True,
        )
    operations.create_index(
        INDEX_NAME,
        TABLE_NAME,
        [COLUMN_NAME],
        schema=schema,
        postgresql_concurrently=True,
    )


def upgrade() -> None:
    bind = op.get_bind()
    schema = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if schema is None:
        raise RuntimeError("env.py did not set the tenant schema for this run")
    # Also required so CONCURRENTLY does not wait forever on our own snapshot.
    bind.commit()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        repair_index(conn, schema)


def downgrade() -> None:
    # f57f35403f6c owns the index and drops it on downgrade. Nothing to undo here.
    pass
