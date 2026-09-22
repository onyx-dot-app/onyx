"""Warm-up must never hold more connections than the pool allows, or ``connect()``
blocks for ``pool_timeout`` and the api server's lifespan fails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from onyx.db.engine.connection_warmup import connections_to_warm_up, warm_up_connections


def _small_pool_engine() -> Engine:
    # pool_timeout of 1s keeps a regression from hanging the suite for 30s.
    return create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=3, max_overflow=2, pool_timeout=1
    )


def _fake_async_engine(pool_size: int) -> tuple[MagicMock, list[AsyncMock]]:
    # No async sqlite driver is installed, so the async engine is a mock over a real
    # QueuePool: sizing runs for real, checkout and release are counted per connection.
    connections: list[AsyncMock] = []

    def connect() -> AsyncMock:
        connection = AsyncMock()
        connections.append(connection)
        return connection

    engine = MagicMock()
    engine.pool = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=pool_size, max_overflow=2
    ).pool
    engine.connect = AsyncMock(side_effect=connect)
    return engine, connections


def test_keeps_smaller_request() -> None:
    engine: Engine = _small_pool_engine()
    assert connections_to_warm_up(engine.pool, 2) == 2


@pytest.mark.asyncio
async def test_warm_up_fits_a_small_pool() -> None:
    sync_engine: Engine = _small_pool_engine()
    async_engine, async_connections = _fake_async_engine(pool_size=3)

    with (
        patch(
            "onyx.db.engine.connection_warmup.get_sqlalchemy_engine",
            return_value=sync_engine,
        ),
        patch(
            "onyx.db.engine.connection_warmup.get_sqlalchemy_async_engine",
            return_value=async_engine,
        ),
    ):
        await warm_up_connections()

    sync_pool = sync_engine.pool
    assert isinstance(sync_pool, QueuePool)
    assert sync_pool.checkedin() == 3
    assert sync_pool.checkedout() == 0

    assert len(async_connections) == 3
    for connection in async_connections:
        assert connection.execute.await_count == 1
        assert connection.close.await_count == 1
