"""
Integration tests for onyx.db.engine.tenant_utils.get_schemas_needing_migration.

These tests require a live database and exercise the function directly,
independent of the alembic migration runner script.

Usage:
    pytest tests/integration/multitenant_tests/test_get_schemas_needing_migration.py -v
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_schemas_needing_migration

_BACKEND_DIR = __file__[: __file__.index("/tests/")]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Engine:
    return SqlEngine.get_engine()


@pytest.fixture
def current_head_rev() -> str:
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
    rev = result.stdout.strip().split()[0]
    assert len(rev) > 0
    return rev


@pytest.fixture
def tenant_schema_at_head(
    engine: Engine, current_head_rev: str
) -> Generator[str, None, None]:
    """Tenant schema with alembic_version already at head — should be excluded."""
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
            text(f'INSERT INTO "{schema}".alembic_version (version_num) VALUES (:rev)'),
            {"rev": current_head_rev},
        )
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


@pytest.fixture
def tenant_schema_empty(engine: Engine) -> Generator[str, None, None]:
    """Tenant schema with no tables — should be included (needs migration)."""
    schema = f"tenant_test_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.commit()

    yield schema

    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


@pytest.fixture
def tenant_schema_stale_rev(engine: Engine) -> Generator[str, None, None]:
    """Tenant schema with a non-head revision — should be included (needs migration)."""
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
# Tests
# ---------------------------------------------------------------------------


def test_classifies_all_cases(
    current_head_rev: str,
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
    tenant_schema_stale_rev: str,
) -> None:
    """Correctly classifies all three schema states:
    - at head      → excluded
    - no table     → included (needs migration)
    - stale rev    → included (needs migration)
    """
    all_schemas = [tenant_schema_at_head, tenant_schema_empty, tenant_schema_stale_rev]
    result = get_schemas_needing_migration(all_schemas, current_head_rev)

    assert tenant_schema_at_head not in result
    assert tenant_schema_empty in result
    assert tenant_schema_stale_rev in result


def test_idempotent(
    current_head_rev: str,
    tenant_schema_at_head: str,
    tenant_schema_empty: str,
) -> None:
    """Calling the function twice returns the same result.

    Verifies that the DROP TABLE IF EXISTS guards correctly clean up temp
    tables so a second call succeeds even if the first left state behind.
    """
    schemas = [tenant_schema_at_head, tenant_schema_empty]

    first = get_schemas_needing_migration(schemas, current_head_rev)
    second = get_schemas_needing_migration(schemas, current_head_rev)

    assert first == second


def test_empty_input(current_head_rev: str) -> None:
    """An empty input list returns immediately without touching the DB."""
    assert get_schemas_needing_migration([], current_head_rev) == []
