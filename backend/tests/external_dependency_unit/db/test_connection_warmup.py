"""Startup warm-up must fit inside the API server's configured connection pool."""

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import QueuePool

from onyx.db.engine import connection_warmup
from onyx.db.engine.sql_engine import ASYNC_DB_API, SYNC_DB_API, build_connection_string

POOL_SIZE = 3
MAX_OVERFLOW = 2


@pytest_asyncio.fixture
async def small_pool_engines() -> AsyncGenerator[tuple[Engine, AsyncEngine], None]:
    # A short pool_timeout turns the old exhaustion hang into a fast failure.
    sync_engine = create_engine(
        build_connection_string(db_api=SYNC_DB_API),
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=2,
    )
    async_engine = create_async_engine(
        build_connection_string(db_api=ASYNC_DB_API),
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=2,
    )
    try:
        yield sync_engine, async_engine
    finally:
        sync_engine.dispose()
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_warm_up_fits_a_pool_smaller_than_the_request(
    small_pool_engines: tuple[Engine, AsyncEngine],
) -> None:
    sync_engine, async_engine = small_pool_engines

    with (
        patch.object(
            connection_warmup, "get_sqlalchemy_engine", return_value=sync_engine
        ),
        patch.object(
            connection_warmup,
            "get_sqlalchemy_async_engine",
            return_value=async_engine,
        ),
    ):
        await connection_warmup.warm_up_connections(
            sync_connections_to_warm_up=20, async_connections_to_warm_up=20
        )

    for pool in (sync_engine.pool, async_engine.pool):
        assert isinstance(pool, QueuePool)
        assert pool.checkedin() == POOL_SIZE
