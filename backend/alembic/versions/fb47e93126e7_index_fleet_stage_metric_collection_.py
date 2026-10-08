"""Index bounded fleet collection of changed indexing-stage summaries.

A concurrent build avoids blocking source writes and recovers invalid indexes
left by an interrupted build. Uses the repository async migration pattern.

Revision ID: fb47e93126e7
Revises: 93b903235ac2
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fb47e93126e7"
down_revision = "93b903235ac2"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_stage_metric_updated_id"


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
            f'ON "{schema}".index_attempt_stage_metric (time_last_event, id)'
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is None:
            return
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{INDEX_NAME}"')
