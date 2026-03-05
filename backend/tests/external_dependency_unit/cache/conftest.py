"""Fixtures for cache backend tests.

Requires a running PostgreSQL instance (and Redis for parity tests).
Run with::

    python -m dotenv -f .vscode/.env run -- pytest tests/external_dependency_unit/cache/
"""

from collections.abc import Generator

import pytest

from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="session", autouse=True)
def _init_db() -> Generator[None, None, None]:
    """Initialize DB engine. Assumes Postgres has migrations applied (e.g. via docker compose)."""
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    yield


@pytest.fixture(autouse=True)
def _tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def pg_cache() -> PostgresCacheBackend:
    return PostgresCacheBackend(TEST_TENANT_ID)


@pytest.fixture
def redis_cache() -> RedisCacheBackend:
    from onyx.redis.redis_pool import redis_pool

    return RedisCacheBackend(redis_pool.get_client(TEST_TENANT_ID))


@pytest.fixture(params=["postgres", "redis"], ids=["postgres", "redis"])
def cache(
    request: pytest.FixtureRequest,
    pg_cache: PostgresCacheBackend,
    redis_cache: RedisCacheBackend,
) -> CacheBackend:
    if request.param == "postgres":
        return pg_cache
    return redis_cache
