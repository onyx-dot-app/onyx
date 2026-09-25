"""
A migration connection keeps its tenant search_path across a commit.

Under pgbouncer transaction pooling a commit can hand the next transaction a
server connection with the default search_path. The pooler cannot run in this
suite, so a `commit` listener issues `RESET search_path` inside every
transaction just before it commits: the session-level setting is gone by the
time the next transaction starts, which is the worst case the pooler produces.
Without the re-apply, `current_schema()` after the commit is public.

Uses the real PostgreSQL the suite runs against and a throwaway schema.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from onyx.db.engine.migration_search_path import (
    install_search_path_reapply,
    pin_search_path_to_schema,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.external_dependency_unit.db.shard_test_utils import (
    create_schema,
    drop_schema,
)


def _pooler_loses_search_path_on_commit(connection: Connection) -> None:
    connection.exec_driver_sql("RESET search_path")


@pytest.fixture
def engine() -> Generator[AsyncEngine, None, None]:
    engine = create_async_engine(build_connection_string(), poolclass=NullPool)
    install_search_path_reapply(engine.sync_engine)
    event.listen(engine.sync_engine, "commit", _pooler_loses_search_path_on_commit)
    yield engine
    engine.sync_engine.dispose()


@pytest.fixture
def schema() -> Generator[str, None, None]:
    name = f"search_path_test_{uuid.uuid4().hex[:8]}"
    sync_engine = create_engine(
        build_connection_string(db_api=SYNC_DB_API), poolclass=NullPool
    )
    create_schema(sync_engine, name)
    yield name
    drop_schema(sync_engine, name)
    sync_engine.dispose()


def _current_schema(connection: Connection) -> str:
    return connection.execute(text("SELECT current_schema()")).scalar_one()


@pytest.mark.asyncio
async def test_search_path_survives_a_mid_run_commit(
    engine: AsyncEngine, schema: str
) -> None:
    async with engine.connect() as connection:

        def run(sync_connection: Connection) -> tuple[str, str, str]:
            pin_search_path_to_schema(sync_connection, schema)
            before = _current_schema(sync_connection)
            # What an index-build migration does mid-run.
            sync_connection.commit()
            after_commit = _current_schema(sync_connection)
            sync_connection.commit()
            after_second = _current_schema(sync_connection)
            return before, after_commit, after_second

        assert await connection.run_sync(run) == (schema, schema, schema)


@pytest.mark.asyncio
async def test_unpinned_connection_is_left_alone(
    engine: AsyncEngine, schema: str
) -> None:
    async with engine.connect() as connection:

        def run(sync_connection: Connection) -> str:
            sync_connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            sync_connection.commit()
            return _current_schema(sync_connection)

        # No pin, so only the simulated pooler reset ran and the SET did not survive.
        assert await connection.run_sync(run) == "public"
