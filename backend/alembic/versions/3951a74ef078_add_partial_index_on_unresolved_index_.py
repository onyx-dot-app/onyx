"""add partial index on unresolved index attempt errors

Revision ID: 3951a74ef078
Revises: ca7cc9a98a6b
Create Date: 2026-10-28 10:20:33.026875

Each docprocessing batch resolves the open errors of its documents. Without
this index the UPDATE scans all of the pair's errors, so its cost grows with
the pair's error history.

index_attempt_errors can be large on a pair with many failures, so the index is
built CONCURRENTLY, as in 90dceb6cd426: commit the migration transaction, then
run the DDL on a dedicated AUTOCOMMIT connection. That connection does not get
the migration connection's search_path, so the statements name the schema.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3951a74ef078"
down_revision = "ca7cc9a98a6b"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_index_attempt_errors_unresolved_cc_pair_document"


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
            f'ON "{schema}".index_attempt_errors '
            "(connector_credential_pair_id, document_id) "
            "WHERE NOT is_resolved"
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{_INDEX_NAME}"')
