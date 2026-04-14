from sqlalchemy import text

from onyx.db.engine.async_sql_engine import get_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import SqlEngine


async def warm_up_connections(
    sync_connections_to_warm_up: int = 20, async_connections_to_warm_up: int = 20
) -> None:
    for host_index, engine in SqlEngine.get_all_engines().items():
        count = max(
            1, sync_connections_to_warm_up // max(1, len(SqlEngine.get_all_engines()))
        )
        connections = [engine.connect() for _ in range(count)]
        for conn in connections:
            conn.execute(text("SELECT 1"))
        for conn in connections:
            conn.close()

        async_engine = get_sqlalchemy_async_engine(host_index)
        a_count = max(
            1, async_connections_to_warm_up // max(1, len(SqlEngine.get_all_engines()))
        )
        async_connections_list = [await async_engine.connect() for _ in range(a_count)]
        for async_conn in async_connections_list:
            await async_conn.execute(text("SELECT 1"))
        for async_conn in async_connections_list:
            await async_conn.close()
