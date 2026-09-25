"""
The index repair in revision da94f38390a5 leaves every schema with a valid
ix_chat_message_chat_session_id: it builds a missing one, rebuilds an invalid
one, and leaves a valid one alone.

Runs the migration's repair function against the real PostgreSQL the suite
uses, on a throwaway schema with a minimal chat_message table. The invalid
state is what a failed CREATE INDEX CONCURRENTLY leaves behind; the catalog
flag is flipped directly to reproduce it.
"""

import importlib.util
import uuid
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "da94f38390a5_rebuild_chat_message_chat_session_id_.py"
)


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("index_repair_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        build_connection_string(db_api=SYNC_DB_API), poolclass=NullPool
    )
    yield engine
    engine.dispose()


@pytest.fixture
def schema(engine: Engine) -> Generator[str, None, None]:
    name = f"index_repair_test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{name}".chat_message '
                "(id SERIAL PRIMARY KEY, chat_session_id UUID NOT NULL)"
            )
        )
    yield name
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))


def _index_oid_and_validity(
    connection: Connection, schema: str, index_name: str
) -> tuple[int, bool] | None:
    row = connection.execute(
        text(
            "SELECT i.indexrelid, i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:name)"
        ),
        {"name": f'"{schema}"."{index_name}"'},
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


def _repair(engine: Engine, migration: ModuleType, schema: str) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        migration.repair_index(conn, schema)


def test_missing_index_is_built(
    engine: Engine, migration: ModuleType, schema: str
) -> None:
    _repair(engine, migration, schema)

    with engine.connect() as connection:
        state = _index_oid_and_validity(connection, schema, migration.INDEX_NAME)
    assert state is not None and state[1] is True


def test_valid_index_is_left_alone(
    engine: Engine, migration: ModuleType, schema: str
) -> None:
    _repair(engine, migration, schema)
    with engine.connect() as connection:
        before = _index_oid_and_validity(connection, schema, migration.INDEX_NAME)

    _repair(engine, migration, schema)

    with engine.connect() as connection:
        after = _index_oid_and_validity(connection, schema, migration.INDEX_NAME)
    # Same relation: nothing was dropped or rebuilt.
    assert before is not None and after == before


def test_invalid_index_is_rebuilt(
    engine: Engine, migration: ModuleType, schema: str
) -> None:
    # A CONCURRENTLY build that fails leaves an INVALID index behind. Two rows
    # with one session id make a unique build under the migration's name fail.
    with engine.begin() as connection:
        connection.execute(
            text(
                f'INSERT INTO "{schema}".chat_message (chat_session_id) '
                "VALUES (:sid), (:sid)"
            ),
            {"sid": str(uuid.uuid4())},
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                f'CREATE UNIQUE INDEX CONCURRENTLY "{migration.INDEX_NAME}" '
                f'ON "{schema}".chat_message (chat_session_id)'
            )
    with engine.connect() as connection:
        before = _index_oid_and_validity(connection, schema, migration.INDEX_NAME)
    assert before is not None and before[1] is False

    _repair(engine, migration, schema)

    with engine.connect() as connection:
        after = _index_oid_and_validity(connection, schema, migration.INDEX_NAME)
    assert after is not None and after[1] is True
    assert after[0] != before[0]
