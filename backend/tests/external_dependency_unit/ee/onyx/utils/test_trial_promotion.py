"""External-dependency unit tests for the trial-business → enterprise promotion.

Covers `ee.onyx.utils.tier.get_tier()` end-to-end against real Redis. The CP
boundary (`fetch_billing_information`) is the only thing mocked — everything
else (cache reads/writes, JSON serialization, datetime comparisons) runs for
real.
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import patch

import pytest

from ee.onyx.configs.app_configs import TENANT_TIER_KEY
from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from ee.onyx.server.tenants.tier_management import get_cached_tier
from ee.onyx.server.tenants.tier_management import update_tenant_tier
from ee.onyx.utils import tier as tier_module
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.models import Tier
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(autouse=True)
def _clean_tier_cache() -> Generator[None, None, None]:
    """Wipe the tier cache before and after each test so runs are isolated."""
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
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
) -> BillingInformation:
    """Build a `BillingInformation` payload with sensible defaults for fields
    the tier resolver does not inspect."""
    now = datetime.now(timezone.utc)
    return BillingInformation(
        stripe_subscription_id="sub_test",
        status="trialing" if trial_end and trial_end > now else "active",
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


def test_trial_business_resolves_to_enterprise() -> None:
    """A BUSINESS tenant with a future trial_end is promoted to ENTERPRISE."""
    future = datetime.now(timezone.utc) + timedelta(days=1)
    update_tenant_tier(TEST_TENANT_ID, CustomerTier.BUSINESS, future)

    assert tier_module.get_tier(TEST_TENANT_ID) == Tier.ENTERPRISE


def test_expired_trial_business_drops_back_to_business() -> None:
    """Once trial_end is in the past, the cached entry resolves to BUSINESS
    without waiting on the next webhook — this is the core defense against
    a delayed CP push."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    update_tenant_tier(TEST_TENANT_ID, CustomerTier.BUSINESS, past)

    assert tier_module.get_tier(TEST_TENANT_ID) == Tier.BUSINESS


def test_non_trial_business_resolves_to_business() -> None:
    """BUSINESS with no trial_end is unaffected by the promotion rule."""
    update_tenant_tier(TEST_TENANT_ID, CustomerTier.BUSINESS, None)

    assert tier_module.get_tier(TEST_TENANT_ID) == Tier.BUSINESS


def test_enterprise_without_trial_resolves_to_enterprise() -> None:
    """A contractual ENTERPRISE tenant is unaffected by the rule (no-op)."""
    update_tenant_tier(TEST_TENANT_ID, CustomerTier.ENTERPRISE, None)

    assert tier_module.get_tier(TEST_TENANT_ID) == Tier.ENTERPRISE


def test_enterprise_with_future_trial_remains_enterprise() -> None:
    """ENTERPRISE + a (nonsense in practice) future trial_end is still
    ENTERPRISE — the promotion rule only fires on BUSINESS."""
    future = datetime.now(timezone.utc) + timedelta(days=1)
    update_tenant_tier(TEST_TENANT_ID, CustomerTier.ENTERPRISE, future)

    assert tier_module.get_tier(TEST_TENANT_ID) == Tier.ENTERPRISE


def test_cache_miss_lazy_refresh_promotes_and_caches() -> None:
    """A cold cache that pulls BUSINESS + future trial_end from CP should
    return ENTERPRISE and write both fields back to the cache as JSON."""
    future = datetime.now(timezone.utc) + timedelta(days=3)
    billing = _billing_info(CustomerTier.BUSINESS, future)

    with patch.object(
        tier_module, "fetch_billing_information", return_value=billing
    ):
        result = tier_module.get_tier(TEST_TENANT_ID)

    assert result == Tier.ENTERPRISE

    cached = get_cached_tier(TEST_TENANT_ID)
    assert cached is not None
    assert cached.customer_tier == CustomerTier.BUSINESS
    # Allow microsecond drift from ISO round-trip.
    assert cached.trial_end is not None
    assert abs((cached.trial_end - future).total_seconds()) < 1


def test_cache_miss_subscription_status_response_falls_back_to_business() -> None:
    """When CP returns the no-subscription shape, we cannot establish a tier;
    `get_tier()` falls back to BUSINESS without caching."""
    response = SubscriptionStatusResponse(subscribed=False, customer_tier=None)

    with patch.object(
        tier_module, "fetch_billing_information", return_value=response
    ):
        result = tier_module.get_tier(TEST_TENANT_ID)

    assert result == Tier.BUSINESS
    # No-op cache write expected on this path.
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    assert redis_client.get(TENANT_TIER_KEY) is None
