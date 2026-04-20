"""Unit tests for the Redis-backed invite + remove-invited rate limits."""

from typing import Any
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.invite_rate_limit import enforce_invite_rate_limit
from onyx.server.manage.invite_rate_limit import enforce_remove_invited_rate_limit


class _StubRedis:
    """In-memory stand-in that mirrors the Lua script's semantics.

    The production rate limiter drives all state via a single EVAL call.
    The stub reimplements that logic in Python so unit tests can assert
    behavior without a live Redis — matching semantics including the
    NX-style TTL that leaves existing TTLs intact on re-increment.
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.eval_fail: Exception | None = None

    def eval(self, _script: str, num_keys: int, *args: Any) -> int:
        if self.eval_fail is not None:
            raise self.eval_fail
        keys = list(args[:num_keys])
        argv = list(args[num_keys:])
        n = int(argv[0])
        for i in range(n):
            key = keys[i]
            increment = int(argv[1 + i * 3])
            limit = int(argv[2 + i * 3])
            if limit > 0 and increment > 0:
                current = self.store.get(key, 0)
                if current + increment > limit:
                    return i + 1
        for i in range(n):
            key = keys[i]
            increment = int(argv[1 + i * 3])
            limit = int(argv[2 + i * 3])
            ttl = int(argv[3 + i * 3])
            if limit > 0 and increment > 0:
                self.store[key] = self.store.get(key, 0) + increment
                if key not in self.ttls:
                    self.ttls[key] = ttl
        return 0


def _stub() -> Redis:
    return cast(Redis, _StubRedis())


def test_invite_allows_under_all_tiers() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 5
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 50
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            500,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=10)

    stub = cast(_StubRedis, redis_client)
    assert stub.store[f"ratelimit:invite_put:admin:{user_id}:day"] == 10
    assert stub.store["ratelimit:invite_put:tenant:day"] == 10
    assert stub.store[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_minute_bucket_blocks_request_flood() -> None:
    """Attacker firing single-email invites rapidly must trip admin/minute."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 5
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 500
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            5000,
        ),
    ):
        for _ in range(5):
            enforce_invite_rate_limit(redis_client, user_id, num_invites=1)

        with pytest.raises(OnyxError) as exc_info:
            enforce_invite_rate_limit(redis_client, user_id, num_invites=1)

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED


def test_invite_bulk_call_does_not_trip_minute_bucket() -> None:
    """Legitimate one-shot bulk call for many users should not hit minute cap."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 5
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 50
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            500,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=20)

    stub = cast(_StubRedis, redis_client)
    assert stub.store[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_admin_daily_cap_enforced() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 50
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=50)
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(redis_client, user_id, num_invites=1)


def test_invite_tenant_daily_cap_enforced_across_admins() -> None:
    """Tenant cap should trip even when traffic comes from multiple admins."""
    redis_client = _stub()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY", 10
        ),
    ):
        enforce_invite_rate_limit(redis_client, uuid4(), num_invites=6)
        enforce_invite_rate_limit(redis_client, uuid4(), num_invites=4)
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(redis_client, uuid4(), num_invites=1)


def test_invite_rejected_request_does_not_consume_budget() -> None:
    """A request that violates a tier must not increment the surviving tiers."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 5
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 50
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY", 10
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=10)
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(redis_client, user_id, num_invites=5)

    stub = cast(_StubRedis, redis_client)
    assert stub.store[f"ratelimit:invite_put:admin:{user_id}:day"] == 10
    assert stub.store["ratelimit:invite_put:tenant:day"] == 10
    assert stub.store[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_zero_new_invites_still_ticks_minute_bucket() -> None:
    """Probes against already-invited emails must still tick the burst guard."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 2
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 500
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=0)
        enforce_invite_rate_limit(redis_client, user_id, num_invites=0)
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(redis_client, user_id, num_invites=0)

    stub = cast(_StubRedis, redis_client)
    assert stub.store.get(f"ratelimit:invite_put:admin:{user_id}:day", 0) == 0
    assert stub.store.get("ratelimit:invite_put:tenant:day", 0) == 0


def test_invite_limit_zero_disables_tier() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 0
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 0
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY", 0
        ),
    ):
        for _ in range(100):
            enforce_invite_rate_limit(redis_client, user_id, num_invites=10)


def test_invite_fails_open_when_redis_unavailable() -> None:
    """Onyx Lite deployments ship without Redis; invite flow must still work."""
    stub = _StubRedis()
    stub.eval_fail = RedisConnectionError("Redis not reachable")
    redis_client = cast(Redis, stub)
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 1
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 1
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY", 1
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=1_000_000)


def test_remove_minute_bucket_blocks_pattern_attack() -> None:
    """PUT→PATCH spam must trip the remove-invited minute bucket."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_MIN",
            3,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_DAY",
            100,
        ),
    ):
        for _ in range(3):
            enforce_remove_invited_rate_limit(redis_client, user_id)
        with pytest.raises(OnyxError):
            enforce_remove_invited_rate_limit(redis_client, user_id)


def test_remove_daily_cap_enforced() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_MIN",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_DAY",
            5,
        ),
    ):
        for _ in range(5):
            enforce_remove_invited_rate_limit(redis_client, user_id)
        with pytest.raises(OnyxError):
            enforce_remove_invited_rate_limit(redis_client, user_id)


def test_ttls_set_on_first_increment_and_not_reset() -> None:
    """TTL must be set on the first increment and must not be reset on later ones."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 100
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 500
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=3)

    stub = cast(_StubRedis, redis_client)
    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:day"] == 24 * 60 * 60
    assert stub.ttls["ratelimit:invite_put:tenant:day"] == 24 * 60 * 60
    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] == 60

    stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] = 999
    with (
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_MIN", 100
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_ADMIN_PER_DAY", 500
        ),
        patch(
            "onyx.server.manage.invite_rate_limit.INVITE_RATE_LIMIT_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(redis_client, user_id, num_invites=3)

    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] == 999
