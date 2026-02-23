"""
Black-box integration tests for the parallel alembic migration runner
(backend/alembic/run_multitenant_migrations.py).

The script is invoked as a subprocess — the same way it would be used in
production.  Tests verify exit codes and stdout messages.

Usage:
    pytest tests/integration/tests/migrations/test_run_multitenant_migrations.py -v
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.db.engine.sql_engine import SqlEngine

# Resolve the backend/ directory once so every helper can use it as cwd.
_BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

# Load get_schemas_needing_migration directly from its file path to avoid the
# naming conflict between the local backend/alembic/ directory and the
# third-party alembic package (which has no __init__.py to shadow it).
_spec = importlib.util.spec_from_file_location(
    "run_multitenant_migrations",
    os.path.join(_BACKEND_DIR, "alembic", "run_multitenant_migrations.py"),
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
get_schemas_needing_migration: Callable[..., list[str]] = (
    _mod.get_schemas_needing_migration
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    *extra_args: str,
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python alembic/run_multitenant_migrations.py`` from the backend/ directory."""
    env = {**os.environ, **(env_override or {})}
    return subprocess.run(
        [sys.executable, "alembic/run_multitenant_migrations.py", *extra_args],
        cwd=_BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Engine:
    return SqlEngine.get_engine()


@pytest.fixture
def current_head_rev() -> str:
    """Get the head revision from the alembic script directory.

    Runs ``alembic heads`` as a subprocess — the same source of truth that
    ``run_multitenant_migrations.py`` uses internally.
    """
    result = subprocess.run(
        ["alembic", "heads", "--resolve-dependencies"],
        cwd=_BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert (
        result.returncode == 0
    ), f"alembic heads failed (exit {result.returncode}):\n{result.stdout}"
    # Output looks like "d5c86e2c6dc6 (head)\n"
    rev = result.stdout.strip().split()[0]
    assert len(rev) > 0
    return rev


@pytest.fixture
def tenant_schema_at_head(
    engine: Engine, current_head_rev: str
) -> Generator[str, None, None]:
    """Create a temporary tenant schema whose alembic_version is at head."""
    schema = f"tenant_test_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                f"(version_num VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(
            text(
                f'INSERT INTO "{schema}".alembic_version (version_num) '
                f"VALUES (:rev)"
            ),
            {"rev": current_head_rev},
        )
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


@pytest.fixture
def tenant_schema_empty(engine: Engine) -> Generator[str, None, None]:
    """Create a temporary tenant schema with no tables at all.

    Alembic will treat it as a fresh schema and run every migration from base
    to head.
    """
    schema = f"tenant_test_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


@pytest.fixture
def tenant_schema_bad_rev(engine: Engine) -> Generator[str, None, None]:
    """Create a tenant schema whose alembic_version points to a non-existent
    revision.  Alembic cannot find a migration path from this revision, so
    it will fail."""
    schema = f"tenant_test_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                f"(version_num VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(
            text(
                f'INSERT INTO "{schema}".alembic_version (version_num) '
                f"VALUES ('00000bad0000')"
            )
        )
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_tenant_schemas_exits_nonzero() -> None:
    """In non-multi-tenant mode there are no tenant_ schemas, so the script
    should print a hint and exit 1."""
    result = _run_script(env_override={"MULTI_TENANT": "false"})
    assert result.returncode == 1
    assert "No tenant schemas found" in result.stdout
    assert "MULTI_TENANT" in result.stdout


def test_at_head_schema_is_skipped(tenant_schema_at_head: str) -> None:
    """A tenant schema already at head should not be targeted for migration."""
    result = _run_script(
        "--jobs",
        "1",
        "--batch-size",
        "50",
        env_override={"MULTI_TENANT": "true"},
    )
    assert result.returncode == 0
    # Our at-head schema should not appear in any batch "started" lines.
    batch_start_lines = [
        line
        for line in result.stdout.splitlines()
        if "Batch" in line and "started" in line
    ]
    for line in batch_start_lines:
        assert tenant_schema_at_head not in line


def test_detects_schemas_needing_migration(
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
) -> None:
    """When some schemas are behind, the script should report how many need
    migration, upgrade them, and succeed."""
    result = _run_script(
        "--jobs",
        "1",
        "--batch-size",
        "50",
        env_override={"MULTI_TENANT": "true"},
    )
    assert result.returncode == 0, f"Script failed:\n{result.stdout}"
    assert "tenants need migration" in result.stdout
    assert "All migrations successful" in result.stdout

    # The empty schema should appear in the batch that was started.
    assert tenant_schema_empty in result.stdout

    # The at-head schema should NOT appear in any batch "started" lines
    # (it was filtered out by get_schemas_needing_migration).
    batch_start_lines = [
        line
        for line in result.stdout.splitlines()
        if "Batch" in line and "started" in line
    ]
    for line in batch_start_lines:
        assert tenant_schema_at_head not in line


def test_failed_migration(
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
    tenant_schema_bad_rev: str,
) -> None:
    """A schema with a bogus alembic revision causes alembic to fail.

    The script should:
    - Exit non-zero (some migrations failed).
    - Still skip the at-head schema.
    - Still attempt the other schemas via the ``continue=true`` retry.
    """
    result = _run_script(
        "--jobs",
        "1",
        "--batch-size",
        "50",
        env_override={"MULTI_TENANT": "true"},
    )
    assert result.returncode == 1, f"Expected failure but got:\n{result.stdout}"
    assert "Some migrations failed" in result.stdout

    # The bad-rev schema should appear in the batch (it needs migration).
    assert tenant_schema_bad_rev in result.stdout

    # The empty schema should also appear (it was attempted via continue=true retry).
    assert tenant_schema_empty in result.stdout

    # The at-head schema should still be skipped.
    batch_start_lines = [
        line
        for line in result.stdout.splitlines()
        if "Batch" in line and "started" in line
    ]
    for line in batch_start_lines:
        assert tenant_schema_at_head not in line


# ---------------------------------------------------------------------------
# Fixtures for direct unit tests of get_schemas_needing_migration
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_schema_stale_rev(engine: Engine) -> Generator[str, None, None]:
    """A tenant schema whose alembic_version is set to a non-head revision.

    Uses a clearly fake revision string so it is never accidentally equal to
    head, but unlike tenant_schema_bad_rev this fixture is for testing
    get_schemas_needing_migration directly (not alembic's migration path).
    """
    schema = f"tenant_test_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                f"(version_num VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(
            text(
                f'INSERT INTO "{schema}".alembic_version (version_num) '
                f"VALUES ('stalerev000000000000')"
            )
        )
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


# ---------------------------------------------------------------------------
# Direct unit tests for get_schemas_needing_migration
# ---------------------------------------------------------------------------


def test_get_schemas_needing_migration_unit(
    current_head_rev: str,
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
    tenant_schema_stale_rev: str,
) -> None:
    """get_schemas_needing_migration correctly classifies all three cases:
    - schema at head      → excluded
    - schema with no alembic_version table → included (needs migration)
    - schema with stale revision           → included (needs migration)
    """
    all_schemas = [tenant_schema_at_head, tenant_schema_empty, tenant_schema_stale_rev]
    result = get_schemas_needing_migration(all_schemas, current_head_rev)

    assert tenant_schema_at_head not in result
    assert tenant_schema_empty in result
    assert tenant_schema_stale_rev in result


def test_get_schemas_needing_migration_idempotent(
    current_head_rev: str,
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
) -> None:
    """Calling the function twice in a row must not fail.

    The first call cleans up _alembic_version_snapshot at the end; the second
    call should succeed even if a previous run left the temp table behind
    (covered by DROP TABLE IF EXISTS at the start of the function).
    """
    schemas = [tenant_schema_at_head, tenant_schema_empty]

    first = get_schemas_needing_migration(schemas, current_head_rev)
    second = get_schemas_needing_migration(schemas, current_head_rev)

    assert first == second


def test_get_schemas_needing_migration_empty_input(current_head_rev: str) -> None:
    """An empty tenant list must return immediately without hitting the DB."""
    result = get_schemas_needing_migration([], current_head_rev)
    assert result == []
