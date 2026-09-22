from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.pool import Pool, QueuePool

from onyx.db.engine.async_sql_engine import get_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import get_sqlalchemy_engine


def connections_to_warm_up(pool: Pool, requested: int) -> int:
    # Only a QueuePool keeps connections, and only pool_size of them. Asking for more
    # than the pool allows blocks for pool_timeout and fails startup.
    if not isinstance(pool, QueuePool):
        return 0
    return min(requested, pool.size())


async def warm_up_connections(
    sync_connections_to_warm_up: int = 20, async_connections_to_warm_up: int = 20
) -> None:
    sync_postgres_engine: Engine = get_sqlalchemy_engine()
    sync_count: int = connections_to_warm_up(
        sync_postgres_engine.pool, sync_connections_to_warm_up
    )
    connections: list[Connection] = [
        sync_postgres_engine.connect() for _ in range(sync_count)
    ]
    for conn in connections:
        conn.execute(text("SELECT 1"))
    for conn in connections:
        conn.close()

    async_postgres_engine: AsyncEngine = get_sqlalchemy_async_engine()
    async_count: int = connections_to_warm_up(
        async_postgres_engine.pool, async_connections_to_warm_up
    )
    async_connections: list[AsyncConnection] = [
        await async_postgres_engine.connect() for _ in range(async_count)
    ]
    for async_conn in async_connections:
        await async_conn.execute(text("SELECT 1"))
    for async_conn in async_connections:
        await async_conn.close()
