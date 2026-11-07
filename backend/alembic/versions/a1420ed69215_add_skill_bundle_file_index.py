"""add partial index on skill bundle files

Revision ID: a1420ed69215
Revises: 1c894e757414
Create Date: 2026-11-07 12:00:00.000000

The hourly orphan skill bundle cleanup selects old skill bundle files. The
partial index keeps that query off the rest of file_record. The index is built
CONCURRENTLY, as in 90dceb6cd426.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1420ed69215"
down_revision = "1c894e757414"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_file_record_skill_bundles"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index does not exist, else pg_index.indisvalid."""
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
            "WHERE file_origin = 'SKILL_BUNDLE'"
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{_INDEX_NAME}"')
