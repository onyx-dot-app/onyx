"""Unit tests for the Redis-backed billing cache."""

from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError

from ee.onyx.server.billing import billing_cache as bc
from ee.onyx.server.billing.billing_cache import BILLING_CACHE_KEY
from ee.onyx.server.billing.billing_cache import cached_fetch_billing_information
from ee.onyx.server.billing.billing_cache import cached_is_tenant_on_trial
from ee.onyx.server.billing.billing_cache import invalidate_billing_cache
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse


def _billing(status: str = "active") -> BillingInformation:
    now = datetime.now(timezone.utc)
    return BillingInformation(
        stripe_subscription_id="sub_123",
        status=status,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        number_of_seats=5,
        cancel_at_period_end=False,
        canceled_at=None,
        trial_start=None,
        trial_end=None,
        seats=5,
        payment_method_enabled=True,
    )


def _fake_redis(
    get_return: bytes | str | None = None,
    raise_on_get: Exception | None = None,
    raise_on_set: Exception | None = None,
) -> MagicMock:
    redis = MagicMock()
    if raise_on_get is not None:
        redis.get = MagicMock(side_effect=raise_on_get)
    else:
        redis.get = MagicMock(return_value=get_return)
    if raise_on_set is not None:
        redis.setex = MagicMock(side_effect=raise_on_set)
    else:
        redis.setex = MagicMock(return_value=True)
    redis.delete = MagicMock(return_value=1)
    return redis


@pytest.fixture(autouse=True)
def _enable_multi_tenant() -> Generator[None, None, None]:
    """The cache is cloud-only; exercise the MULTI_TENANT path by default.
    Single-tenant guard tests opt out with their own ``patch.object``.
    """
    with patch.object(bc, "MULTI_TENANT", True):
        yield


def test_cache_hit_returns_value_without_calling_cp() -> None:
    billing = _billing("trialing")
    cached_bytes = (
        '{"type":"billing","payload":' + billing.model_dump_json() + "}"
    ).encode()
    redis = _fake_redis(get_return=cached_bytes)

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information") as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert isinstance(result, BillingInformation)
    assert result.status == "trialing"
    cp_fetch.assert_not_called()
    redis.get.assert_called_once_with(BILLING_CACHE_KEY.format(tenant_id="tenant_abc"))


def test_cache_miss_fetches_cp_and_writes_with_ttl() -> None:
    billing = _billing("active")
    redis = _fake_redis(get_return=None)

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing) as cp_fetch,
        patch.object(bc, "BILLING_CACHE_TTL_SECONDS", 3600),
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing
    cp_fetch.assert_called_once_with("tenant_abc")
    redis.setex.assert_called_once()
    key, ttl, payload = redis.setex.call_args.args
    assert key == BILLING_CACHE_KEY.format(tenant_id="tenant_abc")
    assert ttl == 3600
    assert '"type": "billing"' in payload or '"type":"billing"' in payload


def test_cache_miss_writes_subscription_status_response_envelope() -> None:
    status = SubscriptionStatusResponse(subscribed=False)
    redis = _fake_redis(get_return=None)

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=status),
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == status
    payload = redis.setex.call_args.args[2]
    assert '"type": "status"' in payload or '"type":"status"' in payload


def test_cached_subscription_status_roundtrip() -> None:
    """SubscriptionStatusResponse written then read back must deserialize to
    the same type — the discriminator is the only thing that lets us tell
    the two union members apart on read.
    """
    status = SubscriptionStatusResponse(subscribed=False)
    cached_bytes = ('{"type":"status","payload":{"subscribed":false}}').encode()
    redis = _fake_redis(get_return=cached_bytes)

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information") as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert isinstance(result, SubscriptionStatusResponse)
    assert result.subscribed is False
    assert result == status
    cp_fetch.assert_not_called()


def test_redis_read_error_falls_through_to_cp_without_crashing() -> None:
    billing = _billing("active")
    redis = _fake_redis(raise_on_get=RedisError("conn refused"))

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing) as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing
    cp_fetch.assert_called_once_with("tenant_abc")
    # Did not try to write (Redis was down).
    redis.setex.assert_not_called()


def test_redis_write_error_is_swallowed_and_value_still_returned() -> None:
    billing = _billing("active")
    redis = _fake_redis(get_return=None, raise_on_set=RedisError("OOM"))

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing),
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing


def test_corrupt_cache_entry_is_refetched_from_cp() -> None:
    billing = _billing("active")
    redis = _fake_redis(get_return=b"not-valid-json{")

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing) as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing
    cp_fetch.assert_called_once_with("tenant_abc")
    # Corrupt entry was overwritten with a fresh good entry.
    redis.setex.assert_called_once()


def test_pydantic_validation_error_on_deserialize_refetches_and_overwrites() -> None:
    """Schema-drift case: valid JSON envelope whose payload no longer matches
    the current BillingInformation schema. Pydantic raises ``ValidationError``,
    which is NOT a subclass of ``ValueError`` in v2 — the cache layer must
    still treat it as a corrupt entry, refetch from CP, and overwrite.
    """
    # Valid JSON + correct envelope shape, but payload is missing every
    # required BillingInformation field → ValidationError on model construction.
    cached_bytes = (
        b'{"type":"billing","payload":{"stripe_subscription_id":"sub_stale"}}'
    )
    redis = _fake_redis(get_return=cached_bytes)
    billing = _billing("active")

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing) as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing
    cp_fetch.assert_called_once_with("tenant_abc")
    redis.setex.assert_called_once()


def test_non_mapping_payload_refetches_and_overwrites() -> None:
    """Payload must be an object — other JSON types are treated as corrupt."""
    cached_bytes = b'{"type":"billing","payload":"not-a-mapping"}'
    redis = _fake_redis(get_return=cached_bytes)
    billing = _billing("active")

    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=billing) as cp_fetch,
    ):
        result = cached_fetch_billing_information("tenant_abc")

    assert result == billing
    cp_fetch.assert_called_once_with("tenant_abc")
    redis.setex.assert_called_once()


def test_tenant_keys_are_isolated() -> None:
    """Cache keys must not collide across tenants."""
    redis = _fake_redis(get_return=None)
    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=_billing("active")),
    ):
        cached_fetch_billing_information("tenant_A")
        cached_fetch_billing_information("tenant_B")

    keys_read = [c.args[0] for c in redis.get.call_args_list]
    assert keys_read == [
        BILLING_CACHE_KEY.format(tenant_id="tenant_A"),
        BILLING_CACHE_KEY.format(tenant_id="tenant_B"),
    ]


def test_is_tenant_on_trial_true_when_status_is_trialing() -> None:
    redis = _fake_redis(get_return=None)
    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(
            bc, "fetch_billing_information", return_value=_billing("trialing")
        ),
    ):
        assert cached_is_tenant_on_trial("tenant_abc") is True


def test_is_tenant_on_trial_false_when_status_is_active() -> None:
    redis = _fake_redis(get_return=None)
    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(bc, "fetch_billing_information", return_value=_billing("active")),
    ):
        assert cached_is_tenant_on_trial("tenant_abc") is False


def test_is_tenant_on_trial_true_when_no_subscription() -> None:
    """Legacy behaviour: a tenant with no subscription on record is
    treated as trial (the old uncached ``is_tenant_on_trial`` returned
    True in this branch)."""
    redis = _fake_redis(get_return=None)
    with (
        patch.object(bc, "get_shared_redis_client", return_value=redis),
        patch.object(
            bc,
            "fetch_billing_information",
            return_value=SubscriptionStatusResponse(subscribed=False),
        ),
    ):
        assert cached_is_tenant_on_trial("tenant_abc") is True


def test_invalidate_drops_cache_entry() -> None:
    redis = _fake_redis()
    with patch.object(bc, "get_shared_redis_client", return_value=redis):
        invalidate_billing_cache("tenant_abc")
    redis.delete.assert_called_once_with(
        BILLING_CACHE_KEY.format(tenant_id="tenant_abc")
    )


def test_invalidate_swallows_redis_errors() -> None:
    redis = _fake_redis()
    redis.delete = MagicMock(side_effect=RedisError("down"))
    with patch.object(bc, "get_shared_redis_client", return_value=redis):
        # No exception bubbles up.
        invalidate_billing_cache("tenant_abc")


def test_single_tenant_fetch_raises_without_touching_redis() -> None:
    """The cache is cloud-only; a single-tenant caller must fail loudly
    rather than open a Redis/control-plane connection a Lite deploy lacks.
    """
    redis = _fake_redis()
    with (
        patch.object(bc, "MULTI_TENANT", False),
        patch.object(bc, "get_shared_redis_client", return_value=redis) as client,
        patch.object(bc, "fetch_billing_information") as cp_fetch,
    ):
        with pytest.raises(RuntimeError):
            cached_fetch_billing_information("tenant_abc")

    client.assert_not_called()
    cp_fetch.assert_not_called()


def test_single_tenant_trial_check_is_false_without_fetch() -> None:
    """Trial limits don't apply in single-tenant; never reach the control plane."""
    redis = _fake_redis()
    with (
        patch.object(bc, "MULTI_TENANT", False),
        patch.object(bc, "get_shared_redis_client", return_value=redis) as client,
        patch.object(bc, "fetch_billing_information") as cp_fetch,
    ):
        assert cached_is_tenant_on_trial("tenant_abc") is False

    client.assert_not_called()
    cp_fetch.assert_not_called()


def test_single_tenant_invalidate_is_noop() -> None:
    """Invalidation must not touch Redis in single-tenant deployments."""
    redis = _fake_redis()
    with (
        patch.object(bc, "MULTI_TENANT", False),
        patch.object(bc, "get_shared_redis_client", return_value=redis) as client,
    ):
        invalidate_billing_cache("tenant_abc")

    client.assert_not_called()
