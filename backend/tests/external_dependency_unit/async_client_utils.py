"""Lifecycle helpers for loop-bound async clients in tests.

Async engines (asyncpg) and async Redis clients bind their connections to the
event loop that created them. A test that creates them on a short-lived loop —
`asyncio.run` or a TestClient portal — must dispose them on that loop before
the loop closes. Engines left over from an earlier test's dead loop can only
be abandoned (`abandon_async_engines`).
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import onyx.db.engine.async_sql_engine as async_sql_engine
import onyx.redis.redis_pool as redis_pool


async def dispose_loop_async_clients() -> None:
    """Dispose async clients owned by the current loop.

    Call this before the loop closes: at the end of an `asyncio.run` body, or
    from a FastAPI lifespan shutdown (see `dispose_async_clients_lifespan`).
    """
    await async_sql_engine.reset_sqlalchemy_async_engine()
    # Close the loop's cached Redis client only when one exists — creating one
    # just to close it would add a Redis dependency to tests that never use it.
    loop = asyncio.get_running_loop()
    redis = redis_pool._async_redis_connections.pop(loop, None)
    if redis is not None:
        await redis.aclose()


@asynccontextmanager
async def dispose_async_clients_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan for TestClient tests.

    The TestClient portal loop owns every async client the app created. This
    lifespan disposes them at shutdown, while that loop still runs.
    """
    yield
    await dispose_loop_async_clients()
