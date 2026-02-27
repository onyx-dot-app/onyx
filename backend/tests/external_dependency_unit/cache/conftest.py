"""Fixtures for cache backend tests.

Requires a running PostgreSQL instance (and Redis for parity tests).
Run with::

    python -m dotenv -f .vscode/.env run -- pytest tests/external_dependency_unit/cache/
"""

from collections.abc import Generator

import pytest
from sqlalchemy import delete

from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import CacheStore
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="session", autouse=True)
def _init_db() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    CacheStore.__table__.create(get_sqlalchemy_engine(), checkfirst=True)
    yield
    with get_session_with_tenant(tenant_id=TEST_TENANT_ID) as session:
        session.execute(delete(CacheStore))
        session.commit()


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
