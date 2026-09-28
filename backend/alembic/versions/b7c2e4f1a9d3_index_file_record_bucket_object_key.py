"""index file_record by bucket and object key

Revision ID: b7c2e4f1a9d3
Revises: ac05f4a21dbd
Create Date: 2026-09-25 16:05:00.000000

The legacy copy checks the file record of every object it copies, and without
an index that check scans the whole table. file_record takes writes on every
upload, so the index is built CONCURRENTLY on a dedicated AUTOCOMMIT connection
after the migration transaction commits, the way e0ea2ae62e51 does, since
op.get_context().autocommit_block() is unusable with this project's env.py.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c2e4f1a9d3"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_file_record_bucket_name_object_key"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index doesn't exist, otherwise pg_index.indisvalid.

    A failed CREATE INDEX CONCURRENTLY leaves an INVALID index behind, which
    a plain existence check would mistake for a finished build.
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
    # env.py's plain SET search_path is session-level and survives this commit.
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
            f'ON "{schema}".file_record (bucket_name, object_key)'
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
