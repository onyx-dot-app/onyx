from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import Engine, create_engine

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.redis.redis_pool import get_async_redis_connection
from tests.external_dependency_unit.db.shard_test_utils import temporary_database


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def redis_client() -> AsyncGenerator[Redis, None]:
    client = await get_async_redis_connection()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def migration_database() -> Generator[Engine, None, None]:
    with contextmanager(temporary_database)("mcp_oauth_migration") as name:
        engine = create_engine(build_connection_string(db_api=SYNC_DB_API, db=name))
        try:
            yield engine
        finally:
            engine.dispose()
