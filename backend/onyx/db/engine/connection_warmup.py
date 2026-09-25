from sqlalchemy import text
from sqlalchemy.pool import Pool, QueuePool

from onyx.db.engine.async_sql_engine import get_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import get_sqlalchemy_engine


def _connections_to_warm_up(pool: Pool, requested: int) -> int:
    # Overflow connections close on check-in, so only the base pool stays warm.
    # Asking for more than the pool can hold blocks until pool_timeout.
    if isinstance(pool, QueuePool):
        return min(requested, pool.size())
    return 0


async def warm_up_connections(
    sync_connections_to_warm_up: int = 20, async_connections_to_warm_up: int = 20
) -> None:
    sync_postgres_engine = get_sqlalchemy_engine()
    connections = [
        sync_postgres_engine.connect()
        for _ in range(
            _connections_to_warm_up(
                sync_postgres_engine.pool, sync_connections_to_warm_up
            )
        )
    ]
    for conn in connections:
        conn.execute(text("SELECT 1"))
    for conn in connections:
        conn.close()

    async_postgres_engine = get_sqlalchemy_async_engine()
    async_connections = [
        await async_postgres_engine.connect()
        for _ in range(
            _connections_to_warm_up(
                async_postgres_engine.pool, async_connections_to_warm_up
            )
        )
    ]
    for async_conn in async_connections:
        await async_conn.execute(text("SELECT 1"))
    for async_conn in async_connections:
        await async_conn.close()
