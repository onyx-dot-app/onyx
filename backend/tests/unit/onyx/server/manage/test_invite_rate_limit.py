"""Unit tests for the invite + remove-invited rate limits."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import invite_rate_limit
from onyx.server.manage.invite_rate_limit import (
    enforce_invite_rate_limit,
    enforce_remove_invited_rate_limit,
)
from tests.unit.fakes import FakeCache


class _StubCache(FakeCache):
    """FakeCache with real TTL bookkeeping and integer counters for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.fail: Exception | None = None

    def get(self, key: str) -> bytes | None:
        if self.fail is not None:
            raise self.fail
        return super().get(key)

    def ttl(self, key: str) -> int:
        return self.expiries.get(key, -2)

    def set_if_absent(
        self, key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> bool:
        # An expired counter is absent, as it is in a real backend.
        if self.expiries.get(key) == -2:
            self.store.pop(key, None)
        return super().set_if_absent(key, value, ex)

    @property
    def counts(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.store.items()}

    @property
    def ttls(self) -> dict[str, int]:
        return self.expiries


def _stub() -> _StubCache:
    return _StubCache()


def test_invite_allows_under_all_tiers() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 5),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 50),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            500,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=10, tenant_id="tenant_a"
        )

    stub = redis_client
    assert stub.counts[f"ratelimit:invite_put:admin:{user_id}:day"] == 10
    assert stub.counts["ratelimit:invite_put:tenant:tenant_a:day"] == 10
    assert stub.counts[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_minute_bucket_blocks_request_flood() -> None:
    """Attacker firing single-email invites rapidly must trip admin/minute."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 5),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 500),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            5000,
        ),
    ):
        for _ in range(5):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=1, tenant_id="tenant_a"
            )

        with pytest.raises(OnyxError) as exc_info:
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=1, tenant_id="tenant_a"
            )

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED


def test_invite_bulk_call_does_not_trip_minute_bucket() -> None:
    """Legitimate one-shot bulk call for many users should not hit minute cap."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 5),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 50),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            500,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=20, tenant_id="tenant_a"
        )

    stub = redis_client
    assert stub.counts[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_admin_daily_cap_enforced() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN",
            1000,
        ),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 50),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=50, tenant_id="tenant_a"
        )
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=1, tenant_id="tenant_a"
            )


def test_invite_tenant_daily_cap_enforced_across_admins() -> None:
    """Tenant cap should trip even when traffic comes from multiple admins."""
    redis_client = _stub()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY",
            1000,
        ),
        patch("onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY", 10),
    ):
        enforce_invite_rate_limit(
            redis_client, uuid4(), num_invites=6, tenant_id="tenant_a"
        )
        enforce_invite_rate_limit(
            redis_client, uuid4(), num_invites=4, tenant_id="tenant_a"
        )
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(
                redis_client, uuid4(), num_invites=1, tenant_id="tenant_a"
            )


def test_invite_rejected_request_does_not_consume_budget() -> None:
    """A request that violates a tier must not increment the surviving tiers."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 5),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 50),
        patch("onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY", 10),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=10, tenant_id="tenant_a"
        )
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=5, tenant_id="tenant_a"
            )

    stub = redis_client
    assert stub.counts[f"ratelimit:invite_put:admin:{user_id}:day"] == 10
    assert stub.counts["ratelimit:invite_put:tenant:tenant_a:day"] == 10
    assert stub.counts[f"ratelimit:invite_put:admin:{user_id}:min"] == 1


def test_invite_zero_new_invites_still_ticks_minute_bucket() -> None:
    """Probes against already-invited emails must still tick the burst guard."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 2),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 500),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=0, tenant_id="tenant_a"
        )
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=0, tenant_id="tenant_a"
        )
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=0, tenant_id="tenant_a"
            )

    stub = redis_client
    assert stub.store.get(f"ratelimit:invite_put:admin:{user_id}:day", 0) == 0
    assert stub.store.get("ratelimit:invite_put:tenant:tenant_a:day", 0) == 0


def test_invite_limit_zero_disables_tier() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 0),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 0),
        patch("onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY", 0),
    ):
        for _ in range(100):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=10, tenant_id="tenant_a"
            )


def test_invite_tenant_bucket_is_isolated_across_tenants() -> None:
    """Regression guard: tenants MUST NOT share the tenant/day counter.
    The tenant_id is also baked into the key string for defence in depth
    on top of the per-tenant Redis prefix applied by ``TenantRedisClient``."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 1000),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 1000),
        patch("onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY", 10),
    ):
        # Tenant A exhausts its own cap.
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=10, tenant_id="tenant_a"
        )
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(
                redis_client, user_id, num_invites=1, tenant_id="tenant_a"
            )

        # Tenant B must still have its full budget.
        enforce_invite_rate_limit(
            redis_client, uuid4(), num_invites=10, tenant_id="tenant_b"
        )

    stub = redis_client
    assert stub.counts["ratelimit:invite_put:tenant:tenant_a:day"] == 10
    assert stub.counts["ratelimit:invite_put:tenant:tenant_b:day"] == 10


def test_invite_fails_open_when_redis_unavailable() -> None:
    """Onyx Lite deployments ship without Redis; invite flow must still work."""
    redis_client = _stub()
    redis_client.fail = RedisConnectionError("Redis not reachable")
    user_id = uuid4()

    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 1),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 1),
        patch("onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY", 1),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=1_000_000, tenant_id="tenant_a"
        )


def test_remove_minute_bucket_blocks_pattern_attack() -> None:
    """PUT→PATCH spam must trip the remove-invited minute bucket."""
    redis_client = _stub()
    user_id = uuid4()

    with (
        patch(
            "onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_MIN",
            3,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_DAY",
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
            "onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_MIN",
            1000,
        ),
        patch(
            "onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_DAY",
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
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 100),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 500),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=3, tenant_id="tenant_a"
        )

    stub = redis_client
    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:day"] == 24 * 60 * 60
    assert stub.ttls["ratelimit:invite_put:tenant:tenant_a:day"] == 24 * 60 * 60
    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] == 60

    stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] = 999
    with (
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_MIN", 100),
        patch("onyx.server.manage.invite_rate_limit._INVITE_ADMIN_PER_DAY", 500),
        patch(
            "onyx.server.manage.invite_rate_limit._INVITE_TENANT_PER_DAY",
            5000,
        ),
    ):
        enforce_invite_rate_limit(
            redis_client, user_id, num_invites=3, tenant_id="tenant_a"
        )

    assert stub.ttls[f"ratelimit:invite_put:admin:{user_id}:min"] == 999


def test_fails_open_when_the_lock_is_busy() -> None:
    """A stuck holder must not block invites: the request passes unrecorded."""
    redis_client = _stub()
    user_id = uuid4()
    assert redis_client.lock(invite_rate_limit._LOCK_KEY).acquire()

    with patch("onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_MIN", 1):
        enforce_remove_invited_rate_limit(redis_client, user_id)
        enforce_remove_invited_rate_limit(redis_client, user_id)

    assert redis_client.counts == {}


def test_lock_is_released_after_a_rejection() -> None:
    redis_client = _stub()
    user_id = uuid4()

    with patch("onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_MIN", 1):
        enforce_remove_invited_rate_limit(redis_client, user_id)
        with pytest.raises(OnyxError):
            enforce_remove_invited_rate_limit(redis_client, user_id)

    assert not redis_client.lock(invite_rate_limit._LOCK_KEY).owned()


@pytest.mark.parametrize(
    ("ttl", "expected_count", "expected_ttl"),
    [
        (0, 3, 1),  # under a second left: keep the window, do not restart it
        (-2, 1, 24 * 60 * 60),  # window ended after the read: restart the count
        (-1, 3, 24 * 60 * 60),  # counter without a TTL gets one
        (500, 3, 500),
    ],
)
def test_window_is_kept_or_restarted_by_the_remaining_ttl(
    ttl: int, expected_count: int, expected_ttl: int
) -> None:
    redis_client = _stub()
    user_id = uuid4()
    day_key = f"ratelimit:invite_remove:admin:{user_id}:day"
    redis_client.set(day_key, 2)
    redis_client.expiries[day_key] = ttl

    with patch("onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_DAY", 100):
        enforce_remove_invited_rate_limit(redis_client, user_id)

    assert redis_client.counts[day_key] == expected_count
    assert redis_client.ttls[day_key] == expected_ttl


def test_no_write_after_the_lock_lease_ends() -> None:
    """A request that outlives its lease must not write a stale count over
    another request's increment. It passes unrecorded."""
    redis_client = _stub()
    user_id = uuid4()
    lock = redis_client.lock(invite_rate_limit._LOCK_KEY)

    def lose_lease(key: str) -> bytes | None:
        lock.release()
        return FakeCache.get(redis_client, key)

    with (
        patch.object(redis_client, "get", side_effect=lose_lease),
        patch("onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_MIN", 1),
    ):
        enforce_remove_invited_rate_limit(redis_client, user_id)

    assert redis_client.counts == {}


def test_a_counter_changed_after_the_read_is_not_overwritten() -> None:
    """With an expired lease another request can count between this request's
    read and its write. The write is a compare-and-swap, so it fails and the
    other request's count stays."""
    redis_client = _stub()
    user_id = uuid4()
    day_key = f"ratelimit:invite_remove:admin:{user_id}:day"
    redis_client.set(day_key, 2, ex=500)

    def other_request_counts(key: str) -> int:
        if key == day_key and redis_client.counts[day_key] == 2:
            redis_client.set(day_key, 3, ex=500)
        return redis_client.expiries.get(key, -2)

    with (
        patch.object(redis_client, "ttl", side_effect=other_request_counts),
        patch("onyx.server.manage.invite_rate_limit._REMOVE_ADMIN_PER_DAY", 100),
    ):
        enforce_remove_invited_rate_limit(redis_client, user_id)

    assert redis_client.counts[day_key] == 3
