"""add partial index on staged connector files

Revision ID: 90dceb6cd426
Revises: bcf79eb7d0a8
Create Date: 2026-10-05 18:50:25.192848

Only staged connector uploads carry the staged_for_cc_pair_id key, so the index
stays small and the hourly staged-file cleanup does not scan the whole table.

file_record can be large and takes writes on every upload, so the index is
built CONCURRENTLY, as in e0ea2ae62e51: commit the migration transaction, then
run the DDL on a dedicated AUTOCOMMIT connection. That connection does not get
the migration connection's search_path, so the statements name the schema.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "90dceb6cd426"
down_revision = "bcf79eb7d0a8"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_file_record_staged_connector_files"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index does not exist, else pg_index.indisvalid. A failed
    concurrent build leaves an INVALID index."""
    row = conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": f'"{schema}"."{_INDEX_NAME}"'},
    ).one_or_none()
    return row[0] if row is not None else None


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    """Commits the migration transaction and returns (bind, tenant schema)."""
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
            conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{_INDEX_NAME}"')
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY "{_INDEX_NAME}" '
            f'ON "{schema}".file_record (created_at) '
            "WHERE file_metadata ? 'staged_for_cc_pair_id'"
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{_INDEX_NAME}"')
