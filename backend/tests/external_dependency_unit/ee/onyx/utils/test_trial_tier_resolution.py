"""External-dependency unit tests for cloud tier resolution.

Covers `ee.onyx.utils.tier.get_tier()` end-to-end against real Redis. The CP
boundary (`fetch_billing_information`) is the only mocked dependency. Cache
reads, writes, JSON serialization, and datetime parsing run for real.

A trialing tenant resolves to the same tier it will hold when the trial
expires.
"""

import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.models import BillingInformation, SubscriptionStatusResponse
from ee.onyx.server.tenants.tier_management import (
    TENANT_TIER_KEY,
    get_cached_tier,
    update_tenant_tier,
)
from ee.onyx.utils import tier as tier_module
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.models import Tier
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture(autouse=True)
def _clean_tier_cache() -> Generator[None, None, None]:
    """Wipe the tier cache before and after each test so runs are isolated."""
    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    redis_client.delete(TENANT_TIER_KEY)
    yield
    redis_client.delete(TENANT_TIER_KEY)


@pytest.fixture(autouse=True)
def _force_multi_tenant() -> Generator[None, None, None]:
    """`get_tier()` short-circuits to the self-hosted path unless MULTI_TENANT.

    The shared_configs module reads the env at import time and caches it in
    a module-level constant, so we patch the constant directly.
    """
    with patch.object(tier_module, "MULTI_TENANT", True):
        yield


def _billing_info(
    customer_tier: CustomerTier,
    trial_end: datetime | None,
    status: str = "active",
) -> BillingInformation:
    """Build a `BillingInformation` payload with sensible defaults for fields
    the tier resolver does not inspect."""
    now = datetime.now(timezone.utc)
    return BillingInformation(
        stripe_subscription_id="sub_test",
        status=status,
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=30),
        number_of_seats=1,
        cancel_at_period_end=False,
        canceled_at=None,
        trial_start=trial_end - timedelta(days=14) if trial_end else None,
        trial_end=trial_end,
        seats=1,
        payment_method_enabled=False,
        customer_tier=customer_tier,
    )


@pytest.mark.parametrize(
    ("customer_tier", "trial_offset", "expected"),
    [
        (CustomerTier.BUSINESS, timedelta(days=1), Tier.BUSINESS),
        (CustomerTier.BUSINESS, timedelta(days=-1), Tier.BUSINESS),
        (CustomerTier.BUSINESS, None, Tier.BUSINESS),
        (CustomerTier.ENTERPRISE, timedelta(days=1), Tier.ENTERPRISE),
        (CustomerTier.ENTERPRISE, None, Tier.ENTERPRISE),
    ],
    ids=[
        "business_active_trial",
        "business_expired_trial",
        "business_no_trial",
        "enterprise_active_trial",
        "enterprise_no_trial",
    ],
)
def test_cached_tier_ignores_trial_state(
    customer_tier: CustomerTier, trial_offset: timedelta | None, expected: Tier
) -> None:
    """A cache hit resolves to the contractual tier. `trial_end` is cached but
    never consulted, so every trial state maps to the same result."""
    trial_end = (
        datetime.now(timezone.utc) + trial_offset if trial_offset is not None else None
    )
    update_tenant_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, customer_tier, trial_end)

    assert tier_module.get_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE) == expected


def test_cache_miss_lazy_refresh_caches_contractual_tier() -> None:
    """A cold cache that pulls BUSINESS + future trial_end from CP returns
    BUSINESS and writes both fields back to the cache as JSON."""
    future = datetime.now(timezone.utc) + timedelta(days=3)
    billing = _billing_info(CustomerTier.BUSINESS, future, status="trialing")

    with patch.object(tier_module, "fetch_billing_information", return_value=billing):
        result = tier_module.get_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    assert result == Tier.BUSINESS

    cached = get_cached_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    assert cached is not None
    assert cached.customer_tier == CustomerTier.BUSINESS
    # Allow microsecond drift from ISO round-trip.
    assert cached.trial_end is not None
    assert abs((cached.trial_end - future).total_seconds()) < 1


def test_cached_naive_trial_end_is_treated_as_none() -> None:
    """A cache entry with a naive `trial_end` ISO string is parsed as `None`
    (logged). The tenant resolves to their contractual tier."""
    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    payload = json.dumps(
        {
            "customer_tier": CustomerTier.BUSINESS.value,
            # Note: no offset → naive.
            "trial_end": "2099-01-01T12:00:00",
        }
    )
    redis_client.set(TENANT_TIER_KEY, payload)

    cached = get_cached_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    assert cached is not None
    assert cached.customer_tier == CustomerTier.BUSINESS
    assert cached.trial_end is None

    # End-to-end: resolves the contractual BUSINESS.
    assert tier_module.get_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE) == Tier.BUSINESS


def test_cp_naive_trial_end_is_not_cached() -> None:
    """The lazy-refresh path drops a naive CP trial_end before caching."""
    naive_future = datetime(2099, 1, 1, 12, 0, 0)  # no tzinfo
    billing = _billing_info(CustomerTier.BUSINESS, naive_future, status="trialing")

    with patch.object(tier_module, "fetch_billing_information", return_value=billing):
        result = tier_module.get_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    assert result == Tier.BUSINESS
    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    raw_cached = redis_client.get(TENANT_TIER_KEY)
    assert raw_cached is not None
    assert json.loads(raw_cached)["trial_end"] is None


def test_cache_miss_subscription_status_response_falls_back_to_business() -> None:
    """A no-subscription response falls back to BUSINESS without caching."""
    response = SubscriptionStatusResponse(subscribed=False, customer_tier=None)

    with patch.object(tier_module, "fetch_billing_information", return_value=response):
        result = tier_module.get_tier(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    assert result == Tier.BUSINESS
    # The resolver does not cache this fallback.
    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    assert redis_client.get(TENANT_TIER_KEY) is None
