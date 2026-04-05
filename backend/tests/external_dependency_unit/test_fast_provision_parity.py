"""
Drift-detection test: verifies that fast tenant provisioning
(metadata.create_all + seed data) produces the same result as
running full Alembic migrations.

If this test fails, it means a migration was added that either:
  1. Creates/alters a table not reflected in models.py (schema drift)
  2. Inserts seed data not replicated in seed_tenant_data.py (data drift)

Fix by updating the relevant source of truth.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ee.onyx.server.tenants.schema_management import fast_provision_tenant_schema
from ee.onyx.server.tenants.schema_management import run_alembic_migrations
from onyx.db.engine.sql_engine import SqlEngine


# Tables whose seed data we compare between the two provisioning paths.
# These are the tables that migrations insert default/seed rows into.
SEED_TABLES = [
    "tool",
    "persona",
    "persona__tool",
    "code_interpreter_server",
    "hierarchy_node",
    '"user"',  # quoted because user is a reserved word
    "key_value_store",
    "search_settings",
]

# Columns to EXCLUDE from seed-data comparison because they contain
# non-deterministic values (timestamps, auto-increment IDs, etc.)
NONDETERMINISTIC_COLUMNS = {
    "id",
    "date_created",
    "time_created",
    "time_updated",
    "created_at",
    "updated_at",
    "oidc_expiry",
    # tool_id in persona__tool differs because auto-increment IDs
    # depend on insertion order
    "tool_id",
}


def _get_engine() -> Engine:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    return SqlEngine.get_engine()


def _create_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()


def _drop_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        # Terminate any lingering connections
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid != pg_backend_pid() "
                f"AND query LIKE '%{schema}%'"
            )
        )
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


def _get_table_columns(engine: Engine, schema: str, table_name: str) -> list[str]:
    """Get ordered column names for a table, excluding non-deterministic ones."""
    clean_table = table_name.strip('"')
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": schema, "table": clean_table},
        )
        return [row[0] for row in result if row[0] not in NONDETERMINISTIC_COLUMNS]


def _get_table_data(
    engine: Engine, schema: str, table_name: str, columns: list[str]
) -> list[tuple[object, ...]]:
    """Fetch all rows from a table, selecting only the given columns."""
    if not columns:
        return []
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    # Order by all columns for deterministic comparison
    with engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{schema}"'))
        result = conn.execute(
            text(f"SELECT {cols_sql} FROM {table_name} ORDER BY {cols_sql}")
        )
        return [tuple(row) for row in result]


def _get_all_tables(engine: Engine, schema: str) -> set[str]:
    """Get all table names in a schema."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            ),
            {"schema": schema},
        )
        return {row[0] for row in result}


def _get_column_info(
    engine: Engine, schema: str
) -> dict[str, list[tuple[str, str, str]]]:
    """Get column definitions for all tables: {table: [(name, type, nullable)]}."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema "
                "ORDER BY table_name, ordinal_position"
            ),
            {"schema": schema},
        )
        columns: dict[str, list[tuple[str, str, str]]] = {}
        for row in result:
            columns.setdefault(row[0], []).append((row[1], row[2], row[3]))
        return columns


@pytest.fixture
def migration_schema() -> Generator[str, None, None]:
    """Create a tenant schema via full Alembic migrations."""
    engine = _get_engine()
    schema = f"tenant_{uuid.uuid4()}"
    _create_schema(engine, schema)
    try:
        run_alembic_migrations(schema)
        yield schema
    finally:
        _drop_schema(engine, schema)


@pytest.fixture
def fast_schema() -> Generator[str, None, None]:
    """Create a tenant schema via fast provisioning."""
    engine = _get_engine()
    schema = f"tenant_{uuid.uuid4()}"
    _create_schema(engine, schema)
    try:
        fast_provision_tenant_schema(schema)
        yield schema
    finally:
        _drop_schema(engine, schema)


class TestFastProvisionParity:
    """Ensure fast provisioning matches full migration output."""

    def test_same_tables_exist(self, migration_schema: str, fast_schema: str) -> None:
        """Both paths should create the same set of tables."""
        engine = _get_engine()
        migration_tables = _get_all_tables(engine, migration_schema)
        fast_tables = _get_all_tables(engine, fast_schema)

        missing = migration_tables - fast_tables
        extra = fast_tables - migration_tables

        assert (
            not missing
        ), f"Tables in migration schema but missing from fast schema: {missing}"
        assert not extra, f"Tables in fast schema but not in migration schema: {extra}"

    def test_same_columns(self, migration_schema: str, fast_schema: str) -> None:
        """Both paths should produce tables with the same columns.

        Columns present in fast schema but missing from migration schema
        indicate missing Alembic migrations (model has columns not yet
        migrated). These are logged as warnings since create_all()
        correctly reflects the model.

        Columns present in migration schema but missing from fast schema
        would indicate a models.py bug and are treated as failures.
        """
        engine = _get_engine()
        migration_cols = _get_column_info(engine, migration_schema)
        fast_cols = _get_column_info(engine, fast_schema)

        # Columns in migration schema that were removed from models.py
        # but never dropped. These are harmless orphans.
        _KNOWN_ORPHANED_COLUMNS: dict[str, set[str]] = {
            "persona_label": {"description"},
            "user_project": {"display_priority"},
        }

        errors: list[str] = []
        warnings: list[str] = []
        all_tables = set(migration_cols.keys()) | set(fast_cols.keys())

        for table in sorted(all_tables):
            m_cols = migration_cols.get(table, [])
            f_cols = fast_cols.get(table, [])
            if m_cols != f_cols:
                m_names = {c[0] for c in m_cols}
                f_names = {c[0] for c in f_cols}
                orphans = _KNOWN_ORPHANED_COLUMNS.get(table, set())
                # Columns in migration but not fast (excluding known orphans)
                missing_from_fast = m_names - f_names - orphans
                # Columns in fast but not migration = missing migration
                extra_in_fast = f_names - m_names
                if missing_from_fast:
                    errors.append(
                        f"Table '{table}': columns in migration but "
                        f"missing from models.py: {missing_from_fast}"
                    )
                if extra_in_fast:
                    warnings.append(
                        f"Table '{table}': columns in models.py but "
                        f"missing migration: {extra_in_fast}"
                    )

        if warnings:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "Columns in models.py without migrations (fast schema "
                "is ahead of migration schema):\n" + "\n".join(warnings)
            )

        assert not errors, (
            "Column differences — models.py is MISSING columns that "
            "migrations create:\n" + "\n".join(errors)
        )

    def test_same_seed_data(self, migration_schema: str, fast_schema: str) -> None:
        """Seed tables should contain the same data in both schemas."""
        engine = _get_engine()
        differences: list[str] = []

        for table in SEED_TABLES:
            # Use columns from migration schema as reference
            columns = _get_table_columns(engine, migration_schema, table)
            if not columns:
                continue

            migration_data = _get_table_data(engine, migration_schema, table, columns)
            fast_data = _get_table_data(engine, fast_schema, table, columns)

            if migration_data != fast_data:
                # Convert to strings for hashable comparison
                m_strs = {str(r) for r in migration_data}
                f_strs = {str(r) for r in fast_data}
                only_migration = m_strs - f_strs
                only_fast = f_strs - m_strs
                differences.append(
                    f"Table '{table}' (cols: {columns}):\n"
                    f"  Only in migration ({len(only_migration)} rows): "
                    f"{list(only_migration)[:3]}\n"
                    f"  Only in fast ({len(only_fast)} rows): "
                    f"{list(only_fast)[:3]}"
                )

        assert (
            not differences
        ), "Seed data differences between migration and fast schema:\n" + "\n".join(
            differences
        )

    def test_alembic_version_matches(
        self, migration_schema: str, fast_schema: str
    ) -> None:
        """Both should be stamped at the same alembic head revision."""
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{migration_schema}"'))
            m_rev = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()

        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{fast_schema}"'))
            f_rev = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()

        assert (
            m_rev == f_rev
        ), f"Alembic version mismatch: migration={m_rev}, fast={f_rev}"
