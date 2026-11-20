"""add index on document doc_updated_at

Revision ID: c828aae2888b
Revises: 3f7b2c9d4e61
Create Date: 2026-11-20 13:59:21.894969

Adds a btree index on document (doc_updated_at DESC NULLS LAST, id DESC). The
postgres_query tool filters documents by updated date and pages them in this
order. Without the index, a date filter on a large connector joins every
document of that connector first: on a deployment with 516k Google Drive
documents, a 7-day listing took about 20s and hit the tool's statement timeout.

document is large and hot, so the index is built CONCURRENTLY on a separate
AUTOCOMMIT connection, as in f57f35403f6c.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c828aae2888b"
down_revision = "3f7b2c9d4e61"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_document_doc_updated_at_id"
LOCK_TIMEOUT = "60s"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None when the index does not exist, otherwise pg_index.indisvalid.

    An interrupted concurrent build leaves an invalid index.
    """
    return conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": f'"{schema}"."{INDEX_NAME}"'},
    ).scalar_one_or_none()


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    """Commit the migration transaction and return (bind, tenant schema)."""
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # env.py owns the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    return bind, schema


def upgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # A plain SET outlives the statement on this pooled connection.
        try:
            state = _index_state(conn, schema)
            if state is True:
                return
            if state is False:
                conn.exec_driver_sql(
                    f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"'
                )
            conn.exec_driver_sql(
                f'CREATE INDEX CONCURRENTLY "{INDEX_NAME}" '
                f'ON "{schema}".document (doc_updated_at DESC NULLS LAST, id DESC)'
            )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
