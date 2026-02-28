"""Tests for PgRedisKVStore's cache layer integration with CacheBackend.

Verifies that the KV store correctly uses the CacheBackend for caching
in front of PostgreSQL: cache hits, cache misses falling through to PG,
cache population after PG reads, cache invalidation on delete, and
graceful degradation when the cache backend raises.

Requires running PostgreSQL.
"""

import json
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete

from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import CacheStore
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.key_value_store.store import PgRedisKVStore
from onyx.key_value_store.store import REDIS_KEY_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="session", autouse=True)
def _init_db() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    engine = get_sqlalchemy_engine()
    CacheStore.__table__.create(engine, checkfirst=True)
    KVStore.__table__.create(engine, checkfirst=True)
    yield
    with get_session_with_tenant(tenant_id=TEST_TENANT_ID) as session:
        session.execute(delete(CacheStore))
        session.execute(delete(KVStore))
        session.commit()


@pytest.fixture(autouse=True)
def _tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(autouse=True)
def _clean_kv(
    _tenant_context: None,
) -> Generator[None, None, None]:
    yield
    with get_session_with_tenant(tenant_id=TEST_TENANT_ID) as session:
        session.execute(delete(KVStore))
        session.execute(delete(CacheStore))
        session.commit()


@pytest.fixture
def pg_cache() -> PostgresCacheBackend:
    return PostgresCacheBackend(TEST_TENANT_ID)


@pytest.fixture
def kv_store(pg_cache: PostgresCacheBackend) -> PgRedisKVStore:
    return PgRedisKVStore(cache=pg_cache)


class TestStoreAndLoad:
    def test_store_populates_cache_and_pg(
        self, kv_store: PgRedisKVStore, pg_cache: PostgresCacheBackend
    ) -> None:
        kv_store.store("k1", {"hello": "world"})

        cached = pg_cache.get(REDIS_KEY_PREFIX + "k1")
        assert cached is not None
        assert json.loads(cached) == {"hello": "world"}

        loaded = kv_store.load("k1")
        assert loaded == {"hello": "world"}

    def test_load_returns_cached_value_without_pg_hit(
        self, pg_cache: PostgresCacheBackend
    ) -> None:
        """If the cache already has the value, PG should not be queried."""
        pg_cache.set(REDIS_KEY_PREFIX + "cached_only", json.dumps({"from": "cache"}))
        kv = PgRedisKVStore(cache=pg_cache)
        assert kv.load("cached_only") == {"from": "cache"}

    def test_load_falls_through_to_pg_on_cache_miss(
        self, kv_store: PgRedisKVStore, pg_cache: PostgresCacheBackend
    ) -> None:
        kv_store.store("k2", [1, 2, 3])

        pg_cache.delete(REDIS_KEY_PREFIX + "k2")
        assert pg_cache.get(REDIS_KEY_PREFIX + "k2") is None

        loaded = kv_store.load("k2")
        assert loaded == [1, 2, 3]

        repopulated = pg_cache.get(REDIS_KEY_PREFIX + "k2")
        assert repopulated is not None
        assert json.loads(repopulated) == [1, 2, 3]

    def test_load_with_refresh_cache_skips_cache(
        self, kv_store: PgRedisKVStore, pg_cache: PostgresCacheBackend
    ) -> None:
        kv_store.store("k3", "original")

        pg_cache.set(REDIS_KEY_PREFIX + "k3", json.dumps("stale"))

        loaded = kv_store.load("k3", refresh_cache=True)
        assert loaded == "original"


class TestDelete:
    def test_delete_removes_from_cache_and_pg(
        self, kv_store: PgRedisKVStore, pg_cache: PostgresCacheBackend
    ) -> None:
        kv_store.store("del_me", "bye")
        kv_store.delete("del_me")

        assert pg_cache.get(REDIS_KEY_PREFIX + "del_me") is None

        with pytest.raises(KvKeyNotFoundError):
            kv_store.load("del_me")

    def test_delete_missing_key_raises(self, kv_store: PgRedisKVStore) -> None:
        with pytest.raises(KvKeyNotFoundError):
            kv_store.delete("nonexistent")


class TestCacheFailureGracefulDegradation:
    def test_store_succeeds_when_cache_set_raises(self) -> None:
        failing_cache = MagicMock(spec=CacheBackend)
        failing_cache.set.side_effect = ConnectionError("cache down")

        kv = PgRedisKVStore(cache=failing_cache)
        kv.store("resilient", {"data": True})

        working_cache = MagicMock(spec=CacheBackend)
        working_cache.get.return_value = None
        kv_reader = PgRedisKVStore(cache=working_cache)
        loaded = kv_reader.load("resilient")
        assert loaded == {"data": True}

    def test_load_falls_through_when_cache_get_raises(self) -> None:
        failing_cache = MagicMock(spec=CacheBackend)
        failing_cache.get.side_effect = ConnectionError("cache down")
        failing_cache.set.side_effect = ConnectionError("cache down")

        kv = PgRedisKVStore(cache=failing_cache)
        kv.store("survive", 42)
        loaded = kv.load("survive")
        assert loaded == 42
