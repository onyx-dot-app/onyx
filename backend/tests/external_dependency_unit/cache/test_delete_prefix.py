"""Prefix cleanup is literal and cannot cross tenant boundaries."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.redis.redis_pool import redis_pool


@pytest.mark.parametrize("suffix", ["plain", "[ab]*?", "percent%_", "back\\slash"])
def test_deletes_literal_prefix_only(cache: CacheBackend, suffix: str) -> None:
    base = f"prefix_{uuid4().hex}:"
    prefix = base + suffix
    matching = [prefix, prefix + ":meta", prefix + ":orphan-chunk"]
    preserved = [base + "other", base + "abXYZ", base + "percentAX"]
    try:
        for key in matching + preserved:
            cache.set(key, b"value")
        cache.delete_prefix(prefix)
        assert all(cache.get(key) is None for key in matching)
        assert all(cache.get(key) == b"value" for key in preserved)
        with pytest.raises(ValueError, match="nonempty"):
            cache.delete_prefix("")
        assert all(cache.get(key) == b"value" for key in preserved)
    finally:
        for key in matching + preserved:
            cache.delete(key)


def test_redis_prefix_deletion_does_not_cross_tenants() -> None:
    tenants = [f"prefix_test_{uuid4().hex}" for _ in range(2)]
    clients = [RedisCacheBackend(redis_pool.get_client(tenant)) for tenant in tenants]
    try:
        for index, client in enumerate(clients):
            client.set("same:key", b"private")
            client.set_add("same:set", str(index))
        assert clients[0].set_members("same:set", limit=10) == [b"0"]
        assert clients[1].set_members("same:set", limit=10) == [b"1"]
        clients[0].delete_prefix("same:")
        assert clients[0].get("same:key") is None
        assert clients[1].get("same:key") == b"private"
    finally:
        for index, client in enumerate(clients):
            client.delete("same:key")
            client.set_remove("same:set", str(index))


def test_postgres_prefix_deletion_does_not_cross_tenants(db_session: Session) -> None:
    schemas = [f"prefix_test_{uuid4().hex}" for _ in range(2)]
    try:
        for schema in schemas:
            db_session.execute(CreateSchema(schema))
            db_session.execute(
                text(
                    f'CREATE TABLE "{schema}".cache_store (LIKE public.cache_store INCLUDING ALL)'
                )
            )
        db_session.commit()
        clients = [PostgresCacheBackend(schema) for schema in schemas]
        for index, client in enumerate(clients):
            client.set("same:key", b"test value")
            client.set_add("same:set", str(index))
        assert clients[0].set_members("same:set", limit=10) == [b"0"]
        assert clients[1].set_members("same:set", limit=10) == [b"1"]
        clients[0].delete_prefix("same:")
        assert clients[0].get("same:key") is None
        assert clients[1].get("same:key") == b"test value"
    finally:
        db_session.rollback()
        for schema in schemas:
            db_session.execute(DropSchema(schema, cascade=True, if_exists=True))
        db_session.commit()


def test_prefix_deletion_covers_multiple_scan_batches(cache: CacheBackend) -> None:
    prefix = f"chunks_{uuid4().hex}:"
    keys = [f"{prefix}{index}" for index in range(205)]
    try:
        for key in keys:
            cache.set(key, b"orphaned stream bytes")
        cache.delete_prefix(prefix)
        assert all(cache.get(key) is None for key in keys)
    finally:
        for key in keys:
            cache.delete(key)


def test_batch_exists_excludes_expired_values(cache: CacheBackend) -> None:
    prefix = f"existence_{uuid4().hex}:"
    live, expired, missing = [
        prefix + suffix for suffix in ("live", "expired", "missing")
    ]
    try:
        cache.set(live, b"private content")
        cache.set(expired, b"expired content")
        cache.expire(expired, 0)
        missing_keys = [f"{missing}:{index}" for index in range(1001)]
        assert cache.exists_many([live, expired, *missing_keys, live]) == {live}
        assert cache.exists_many([]) == set()
    finally:
        cache.delete(live)
        cache.delete(expired)
