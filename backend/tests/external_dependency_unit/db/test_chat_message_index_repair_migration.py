"""
The index repair in revision da94f38390a5 leaves every schema with a valid
ix_chat_message_chat_session_id: it builds a missing one, rebuilds an invalid
one, and leaves a valid one alone.

Runs the migration's repair function against the real PostgreSQL the suite
uses, on a throwaway schema with a minimal chat_message table. The invalid
state is what a failed CREATE INDEX CONCURRENTLY leaves behind, reproduced
here with a unique build over duplicate rows.
"""

import importlib.util
import uuid
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.external_dependency_unit.db.shard_test_utils import (
    create_schema,
    drop_schema,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "da94f38390a5_rebuild_chat_message_chat_session_id_.py"
)

_pg_index = sa.table("pg_index", sa.column("indexrelid"), sa.column("indisvalid"))


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
def chat_message(
    engine: Engine, migration: ModuleType
) -> Generator[sa.Table, None, None]:
    """A throwaway schema holding a minimal chat_message table."""
    schema = f"index_repair_test_{uuid.uuid4().hex[:8]}"
    create_schema(engine, schema)
    table = sa.Table(
        migration.TABLE_NAME,
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(migration.COLUMN_NAME, UUID(as_uuid=True), nullable=False),
        schema=schema,
    )
    table.create(engine)
    yield table
    drop_schema(engine, schema)


def _index_oid_and_validity(
    connection: Connection, schema: str, index_name: str
) -> tuple[int, bool] | None:
    row = connection.execute(
        sa.select(_pg_index.c.indexrelid, _pg_index.c.indisvalid).where(
            _pg_index.c.indexrelid == sa.func.to_regclass(f'"{schema}"."{index_name}"')
        )
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


def _repair(engine: Engine, migration: ModuleType, schema: str) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        migration.repair_index(conn, schema)


def _state(
    engine: Engine, migration: ModuleType, schema: str
) -> tuple[int, bool] | None:
    with engine.connect() as connection:
        return _index_oid_and_validity(connection, schema, migration.INDEX_NAME)


def test_missing_index_is_built(
    engine: Engine, migration: ModuleType, chat_message: sa.Table
) -> None:
    schema = str(chat_message.schema)
    _repair(engine, migration, schema)

    state = _state(engine, migration, schema)
    assert state is not None and state[1] is True


def test_valid_index_is_left_alone(
    engine: Engine, migration: ModuleType, chat_message: sa.Table
) -> None:
    schema = str(chat_message.schema)
    _repair(engine, migration, schema)
    before = _state(engine, migration, schema)

    _repair(engine, migration, schema)

    # Same relation: nothing was dropped or rebuilt.
    assert before is not None and _state(engine, migration, schema) == before


def test_invalid_index_is_rebuilt(
    engine: Engine, migration: ModuleType, chat_message: sa.Table
) -> None:
    schema = str(chat_message.schema)
    # A CONCURRENTLY build that fails leaves an INVALID index behind. Two rows
    # with one session id make a unique build under the migration's name fail.
    session_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            chat_message.insert(),
            [{migration.COLUMN_NAME: session_id}, {migration.COLUMN_NAME: session_id}],
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        with pytest.raises(IntegrityError):
            sa.Index(
                migration.INDEX_NAME,
                chat_message.c[migration.COLUMN_NAME],
                unique=True,
                postgresql_concurrently=True,
            ).create(conn)
    before = _state(engine, migration, schema)
    assert before is not None and before[1] is False

    _repair(engine, migration, schema)

    after = _state(engine, migration, schema)
    assert after is not None and after[1] is True
    assert after[0] != before[0]
