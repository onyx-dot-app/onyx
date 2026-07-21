"""External dependency tests for ``TenantRedis``.

These tests run against a real Redis and verify the prefixing contract on which
multi-tenant isolation depends:

  * Writes through ``TenantRedis`` land under the tenant-prefixed key.
  * Reads through ``TenantRedis`` find data written under the same prefixed key,
    and never see another tenant's keys.
  * Methods that return keys (``scan_iter``, ``blpop``) strip the prefix on the
    way out, so callers don't see the tenant id leaked back.
  * Lua scripts run via ``EVAL`` see prefixed keys but unmodified ARGV.

Each test uses a unique tenant id so concurrent / repeated runs cannot collide;
per-test cleanup wipes every key under that tenant's namespace.
"""

import time
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from redis import Redis

from onyx.redis.redis_pool import get_raw_redis_client
from onyx.redis.redis_pool import redis_pool
from onyx.redis.redis_pool import TenantRedis


def _unique_tenant() -> str:
    return f"tenant_test_{uuid4().hex[:12]}"


def _unique_key(prefix: str = "k") -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@pytest.fixture
def tenant_id() -> str:
    return _unique_tenant()


@pytest.fixture
def tenant_redis(tenant_id: str) -> Generator[TenantRedis, None, None]:
    client = cast(TenantRedis, redis_pool.get_client(tenant_id))
    yield client
    # Wipe everything that this tenant touched so the test is hermetic.
    raw = get_raw_redis_client()
    pattern = f"{tenant_id}:*"
    keys = list(raw.scan_iter(match=pattern))
    if keys:
        raw.delete(*keys)


@pytest.fixture
def raw_redis() -> Redis:
    return get_raw_redis_client()


# ------------------------------------------------------------------------------
# Writes land under the prefixed key
# ------------------------------------------------------------------------------


class TestPrefixingOnWrite:
    def test_set_writes_to_prefixed_key(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key = _unique_key()
        tenant_redis.set(key, "value")
        # Raw client sees the prefixed key.
        assert raw_redis.get(f"{tenant_id}:{key}") == b"value"
        # And nothing under the bare key.
        assert raw_redis.get(key) is None

    def test_hset_writes_to_prefixed_key(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key = _unique_key("h")
        tenant_redis.hset(key, "field", "value")
        assert raw_redis.hget(f"{tenant_id}:{key}", "field") == b"value"

    def test_incr_writes_to_prefixed_key(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key = _unique_key("c")
        tenant_redis.incr(key)
        tenant_redis.incr(key)
        assert raw_redis.get(f"{tenant_id}:{key}") == b"2"

    def test_rpush_writes_to_prefixed_key(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key = _unique_key("q")
        tenant_redis.rpush(key, "a")
        tenant_redis.rpush(key, "b")
        assert raw_redis.lrange(f"{tenant_id}:{key}", 0, -1) == [b"a", b"b"]


# ------------------------------------------------------------------------------
# Write/read pairs target the same key
# ------------------------------------------------------------------------------


class TestRoundTrip:
    def test_set_get(self, tenant_redis: TenantRedis) -> None:
        key = _unique_key()
        tenant_redis.set(key, "value")
        assert tenant_redis.get(key) == b"value"

    def test_hset_hget(self, tenant_redis: TenantRedis) -> None:
        key = _unique_key("h")
        tenant_redis.hset(key, "field", "value")
        assert tenant_redis.hget(key, "field") == b"value"

    def test_hset_hmget(self, tenant_redis: TenantRedis) -> None:
        # The hmget bug from this PR: hset was prefixed but hmget wasn't, so
        # reads returned [None, ...] for everything written via hset.
        key = _unique_key("h")
        tenant_redis.hset(key, "f1", "v1")
        tenant_redis.hset(key, "f2", "v2")
        assert tenant_redis.hmget(key, ["f1", "f2", "missing"]) == [
            b"v1",
            b"v2",
            None,
        ]

    def test_incr_then_get_sees_same_counter(self, tenant_redis: TenantRedis) -> None:
        # The incr bug from this PR: incr wrote to the bare key, get read from
        # the prefixed key, so the counter always read as 0.
        key = _unique_key("c")
        tenant_redis.incr(key)
        tenant_redis.incr(key)
        tenant_redis.incr(key)
        assert tenant_redis.get(key) == b"3"


# ------------------------------------------------------------------------------
# Tenant isolation
# ------------------------------------------------------------------------------


class TestTenantIsolation:
    def test_other_tenant_cannot_read_my_key(self, tenant_redis: TenantRedis) -> None:
        key = _unique_key()
        tenant_redis.set(key, "mine")

        other_tenant = _unique_tenant()
        other = cast(TenantRedis, redis_pool.get_client(other_tenant))
        try:
            assert other.get(key) is None
        finally:
            raw = get_raw_redis_client()
            for k in raw.scan_iter(match=f"{other_tenant}:*"):
                raw.delete(k)

    def test_other_tenant_cannot_pop_my_blpop_key(
        self, tenant_redis: TenantRedis
    ) -> None:
        key = _unique_key("q")
        tenant_redis.rpush(key, "mine")

        other_tenant = _unique_tenant()
        other = cast(TenantRedis, redis_pool.get_client(other_tenant))
        try:
            assert other.blpop([key], timeout=1) is None
        finally:
            raw = get_raw_redis_client()
            for k in raw.scan_iter(match=f"{other_tenant}:*"):
                raw.delete(k)


# ------------------------------------------------------------------------------
# Idempotent prefixing
# ------------------------------------------------------------------------------


class TestIdempotentPrefix:
    def test_set_with_already_prefixed_key_does_not_double_prefix(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key = _unique_key()
        tenant_redis.set(f"{tenant_id}:{key}", "value")
        # Single prefix in storage.
        assert raw_redis.get(f"{tenant_id}:{key}") == b"value"
        # No double-prefixed key was created.
        assert raw_redis.get(f"{tenant_id}:{tenant_id}:{key}") is None


# ------------------------------------------------------------------------------
# TTL family round-trip — was broken before `expire` was added to wraps
# ------------------------------------------------------------------------------


class TestTTLFamily:
    def test_set_then_expire_then_ttl(self, tenant_redis: TenantRedis) -> None:
        # The expire bug: set wrote to the prefixed key, expire ran on the bare
        # key, so the TTL silently no-op'd. Pin both states explicitly:
        #   * After set, the key exists with no TTL (Redis returns -1).
        #   * After expire, the key has a TTL in (0, 60].
        # If expire were broken, the second assertion would still see -1 here.
        key = _unique_key()
        tenant_redis.set(key, "value")
        assert cast(int, tenant_redis.ttl(key)) == -1
        tenant_redis.expire(key, 60)
        ttl = cast(int, tenant_redis.ttl(key))
        assert 0 < ttl <= 60

    def test_setex_then_ttl(self, tenant_redis: TenantRedis) -> None:
        # Sanity precondition: key doesn't exist yet (TTL = -2).
        key = _unique_key()
        assert cast(int, tenant_redis.ttl(key)) == -2
        tenant_redis.setex(key, 60, "value")
        ttl = cast(int, tenant_redis.ttl(key))
        assert 0 < ttl <= 60


# ------------------------------------------------------------------------------
# scan_iter strips returned prefix
# ------------------------------------------------------------------------------


class TestScanIter:
    def test_scan_iter_returns_keys_without_prefix(
        self, tenant_redis: TenantRedis
    ) -> None:
        match_prefix = _unique_key("scan")
        keys = {f"{match_prefix}_{i}" for i in range(3)}
        for k in keys:
            tenant_redis.set(k, "v")

        returned = {
            k.decode() if isinstance(k, bytes) else k
            for k in tenant_redis.scan_iter(match=f"{match_prefix}_*")
        }
        assert returned == keys


# ------------------------------------------------------------------------------
# BLPOP — input prefixing, return-key un-prefixing, multi-key, isolation
# ------------------------------------------------------------------------------


class TestBlpop:
    def test_blpop_returns_key_without_prefix(self, tenant_redis: TenantRedis) -> None:
        # The BLPOP return-leak bug: redis returns (key, value) where key is the
        # prefixed name we sent. The wrapper must strip the prefix so callers
        # see the same key they passed in.
        key = _unique_key("q")
        tenant_redis.rpush(key, "value")

        # Cast: the inherited Redis.blpop is typed as `Awaitable[list] | list`,
        # but our wrapper returns `tuple[bytes, bytes] | None`.
        result = cast(
            tuple[bytes, bytes] | None,
            tenant_redis.blpop([key], timeout=1),
        )
        assert result is not None
        popped_key, popped_value = result
        assert popped_key == key.encode()
        assert popped_value == b"value"

    def test_blpop_multi_key_returns_correct_unprefixed_key(
        self, tenant_redis: TenantRedis
    ) -> None:
        # BLPOP with multiple keys returns whichever fired; that key must come
        # back unprefixed even when it isn't the first one.
        empty_key = _unique_key("empty")
        loaded_key = _unique_key("loaded")
        tenant_redis.rpush(loaded_key, "value")

        result = cast(
            tuple[bytes, bytes] | None,
            tenant_redis.blpop([empty_key, loaded_key], timeout=1),
        )
        assert result is not None
        popped_key, popped_value = result
        assert popped_key == loaded_key.encode()
        assert popped_value == b"value"

    def test_blpop_timeout_returns_none(self, tenant_redis: TenantRedis) -> None:
        key = _unique_key("q")
        # Nothing pushed; should time out.
        start = time.monotonic()
        result = tenant_redis.blpop([key], timeout=1)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed >= 0.9


# ------------------------------------------------------------------------------
# EVAL — Lua sees prefixed keys; ARGV is untouched; script string is untouched
# ------------------------------------------------------------------------------


class TestEval:
    def test_eval_writes_under_prefixed_key(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        # Script does SET KEYS[1] = ARGV[1]. We pass the bare key and value;
        # raw client must see the prefixed key with the unmodified value.
        key = _unique_key("lua")
        tenant_redis.eval("redis.call('SET', KEYS[1], ARGV[1])", 1, key, "value")
        assert raw_redis.get(f"{tenant_id}:{key}") == b"value"

    def test_eval_can_read_what_set_wrote(self, tenant_redis: TenantRedis) -> None:
        # Round-trip through wrapped methods: set via TenantRedis.set, read via
        # EVAL. Both must target the same prefixed key.
        key = _unique_key("lua")
        tenant_redis.set(key, "from_set")
        result = tenant_redis.eval("return redis.call('GET', KEYS[1])", 1, key)
        assert result == b"from_set"

    def test_eval_with_multiple_keys_prefixes_each(
        self,
        tenant_redis: TenantRedis,
        tenant_id: str,
        raw_redis: Redis,
    ) -> None:
        key1 = _unique_key("lua1")
        key2 = _unique_key("lua2")
        tenant_redis.eval(
            "redis.call('SET', KEYS[1], ARGV[1]); "
            "redis.call('SET', KEYS[2], ARGV[2])",
            2,
            key1,
            key2,
            "v1",
            "v2",
        )
        assert raw_redis.get(f"{tenant_id}:{key1}") == b"v1"
        assert raw_redis.get(f"{tenant_id}:{key2}") == b"v2"

    def test_eval_with_zero_keys_does_not_prefix_argv(
        self, tenant_redis: TenantRedis
    ) -> None:
        # numkeys=0 means everything after is ARGV. Nothing should be prefixed;
        # the script returns ARGV[1] verbatim.
        sentinel = "argv_value_not_a_key"
        result = tenant_redis.eval("return ARGV[1]", 0, sentinel)
        assert result == sentinel.encode()
