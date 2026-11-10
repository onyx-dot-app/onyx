"""index skill bundle cleanup and reference checks

Revision ID: a1420ed69215
Revises: 6476b236ec97
Create Date: 2026-11-07 12:00:00.000000

Partial indexes select old skill files and check retained file references.
Build them CONCURRENTLY, as in 90dceb6cd426.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1420ed69215"
down_revision = "6476b236ec97"
branch_labels = None
depends_on = None

_INDEXES = (
    (
        "ix_file_record_skill_bundles",
        "file_record",
        "created_at",
        "file_origin = 'SKILL_BUNDLE'",
    ),
    (
        "ix_skill_version_bundle_file_id",
        "skill_version",
        "bundle_file_id",
        "bundle_file_id IS NOT NULL",
    ),
    (
        "ix_skill_bundle_file_id",
        "skill",
        "bundle_file_id",
        "bundle_file_id IS NOT NULL",
    ),
)


def _index_state(conn: sa.engine.Connection, schema: str, name: str) -> bool | None:
    """None if the index does not exist, else pg_index.indisvalid."""
    row = conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": f'"{schema}"."{name}"'},
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
        for name, table, column, predicate in _INDEXES:
            state = _index_state(conn, schema, name)
            if state is True:
                continue
            if state is False:
                conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{name}"')
            conn.exec_driver_sql(
                f'CREATE INDEX CONCURRENTLY "{name}" '
                f'ON "{schema}"."{table}" ("{column}") WHERE {predicate}'
            )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()

    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for name, _, _, _ in reversed(_INDEXES):
            if _index_state(conn, schema, name) is not None:
                conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY "{schema}"."{name}"')
