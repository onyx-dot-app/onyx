from collections.abc import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import Engine, create_engine

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.redis.redis_pool import get_async_redis_connection


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def redis_client() -> AsyncGenerator[Redis, None]:
    client = await get_async_redis_connection()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def migration_database() -> Generator[Engine, None, None]:
    name = f"mcp_oauth_migration_{uuid4().hex}"
    admin = create_engine(
        build_connection_string(db_api=SYNC_DB_API), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(build_connection_string(db_api=SYNC_DB_API, db=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()
