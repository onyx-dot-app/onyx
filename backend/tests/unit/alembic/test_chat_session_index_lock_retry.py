"""Guards the chat_session index migration's bounded wait: a lock timeout from
either driver shape retries after dropping the INVALID leftover, any other
error raises at once, and the attempt limit ends in a RuntimeError."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import asyncpg.exceptions
import psycopg2.errors
import pytest
from sqlalchemy.exc import DBAPIError

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "e0ea2ae62e51_add_index_on_chat_session_user_id_and_.py"
)
MODULE_NAME = "migration_e0ea2ae62e51"


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _psycopg2_lock_timeout() -> DBAPIError:
    return DBAPIError("CREATE INDEX", {}, psycopg2.errors.LockNotAvailable())


def _asyncpg_lock_timeout() -> DBAPIError:
    # SQLAlchemy's asyncpg adapter raises its own error from the driver's.
    adapter_error = Exception("canceling statement due to lock timeout")
    adapter_error.__cause__ = asyncpg.exceptions.LockNotAvailableError()
    return DBAPIError("CREATE INDEX", {}, adapter_error)


def _other_error() -> DBAPIError:
    return DBAPIError("CREATE INDEX", {}, psycopg2.errors.UndefinedTable())


def test_is_lock_timeout_matches_both_driver_shapes(migration: ModuleType) -> None:
    assert migration._is_lock_timeout(_psycopg2_lock_timeout())
    assert migration._is_lock_timeout(_asyncpg_lock_timeout())
    assert not migration._is_lock_timeout(_other_error())


def test_build_retries_after_dropping_invalid_index(migration: ModuleType) -> None:
    conn: MagicMock = MagicMock()
    conn.exec_driver_sql.side_effect = [
        None,  # SET lock_timeout
        _asyncpg_lock_timeout(),  # first CREATE times out
        None,  # DROP of the INVALID leftover
        None,  # second CREATE succeeds
    ]
    with (
        patch.object(migration, "_index_state", side_effect=[None, False]),
        patch.object(migration.time, "sleep") as sleep,
    ):
        migration._build_index(conn, "tenant_a")

    statements: list[str] = [
        call.args[0] for call in conn.exec_driver_sql.call_args_list
    ]
    assert statements[0] == f"SET lock_timeout = '{migration.LOCK_TIMEOUT}'"
    assert statements[1].startswith("CREATE INDEX CONCURRENTLY")
    assert statements[2].startswith("DROP INDEX CONCURRENTLY")
    assert statements[3].startswith("CREATE INDEX CONCURRENTLY")
    sleep.assert_called_once_with(migration.RETRY_DELAY_SEC)


def test_build_raises_other_errors_at_once(migration: ModuleType) -> None:
    conn: MagicMock = MagicMock()
    conn.exec_driver_sql.side_effect = [None, _other_error()]
    with (
        patch.object(migration, "_index_state", return_value=None),
        patch.object(migration.time, "sleep") as sleep,
        pytest.raises(DBAPIError),
    ):
        migration._build_index(conn, "tenant_a")
    sleep.assert_not_called()


def test_build_gives_up_after_max_attempts(migration: ModuleType) -> None:
    conn: MagicMock = MagicMock()
    conn.exec_driver_sql.side_effect = [None] + [
        _psycopg2_lock_timeout()
    ] * migration.MAX_BUILD_ATTEMPTS
    with (
        patch.object(migration, "_index_state", return_value=None),
        patch.object(migration.time, "sleep") as sleep,
        pytest.raises(RuntimeError, match="tenant_a"),
    ):
        migration._build_index(conn, "tenant_a")
    assert sleep.call_count == migration.MAX_BUILD_ATTEMPTS - 1
