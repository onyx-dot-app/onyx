"""External-dependency unit tests for the license metadata cache.

Runs `update_license_cache` and `get_cached_license_metadata` end-to-end
against real Redis. The cache singleton + 24h TTL + tier round-trip are
what makes a license re-upload reflect immediately in `get_tier()` — verified
manually during BUSINESS → ENTERPRISE → BUSINESS lifecycle testing.
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.db.license import LICENSE_CACHE_TTL_SECONDS
from ee.onyx.db.license import LICENSE_METADATA_KEY
from ee.onyx.db.license import update_license_cache
from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import PlanType
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(autouse=True)
def _setup(
    db_session: Session,  # noqa: ARG001 — fixture requested only for its side-effect (SQL engine init); pytest binds by name
    tenant_context: None,  # noqa: ARG001 — fixture requested only for its side-effect (tenant contextvar); pytest binds by name
) -> Generator[None, None, None]:
    """Per-test setup:

    - `db_session` (from parent conftest) initializes the SQL engine —
      `update_license_cache` calls `get_used_seats` which needs the engine.
    - `tenant_context` (from parent conftest) sets the tenant contextvar so
      the implicit `get_session_with_current_tenant()` inside `get_used_seats`
      resolves to the test tenant.
    - We wipe the license cache before and after each test for isolation.
    """
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    redis_client.delete(LICENSE_METADATA_KEY)
    yield
    redis_client.delete(LICENSE_METADATA_KEY)


def _payload(
    customer_tier: CustomerTier | None = CustomerTier.ENTERPRISE,
) -> LicensePayload:
    """Build a minimal valid LicensePayload for cache round-trips."""
    now = datetime.now(timezone.utc)
    return LicensePayload(
        version="1.0",
        tenant_id="tenant_test_cache",
        organization_name="Cache Test Org",
        issued_at=now,
        expires_at=now + timedelta(days=365),
        seats=100,
        plan_type=PlanType.ANNUAL,
        customer_tier=customer_tier,
    )


def test_writes_under_expected_key() -> None:
    """The cache layer writes to the documented LICENSE_METADATA_KEY."""
    update_license_cache(
        _payload(), source=LicenseSource.MANUAL_UPLOAD, tenant_id=TEST_TENANT_ID
    )
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    assert redis_client.exists(LICENSE_METADATA_KEY) == 1


def test_sets_24h_ttl() -> None:
    """The cache entry expires after LICENSE_CACHE_TTL_SECONDS (24h)."""
    update_license_cache(
        _payload(), source=LicenseSource.AUTO_FETCH, tenant_id=TEST_TENANT_ID
    )
    redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
    ttl = redis_client.ttl(LICENSE_METADATA_KEY)
    # Allow a few seconds of drift between SET and TTL read.
    assert LICENSE_CACHE_TTL_SECONDS - 10 <= ttl <= LICENSE_CACHE_TTL_SECONDS


def test_round_trip_preserves_tier_and_source() -> None:
    """Cached metadata round-trips customer_tier and source unchanged."""
    update_license_cache(
        _payload(CustomerTier.BUSINESS),
        source=LicenseSource.AUTO_FETCH,
        tenant_id=TEST_TENANT_ID,
    )
    metadata = get_cached_license_metadata(tenant_id=TEST_TENANT_ID)
    assert metadata is not None
    assert metadata.customer_tier == CustomerTier.BUSINESS
    assert metadata.source == LicenseSource.AUTO_FETCH


def test_singleton_subsequent_write_overwrites() -> None:
    """Re-upload replaces the cached entry; no accumulation. Makes live
    tier flips (BUSINESS↔ENTERPRISE) reactive within a single request."""
    update_license_cache(
        _payload(CustomerTier.BUSINESS),
        source=LicenseSource.MANUAL_UPLOAD,
        tenant_id=TEST_TENANT_ID,
    )
    update_license_cache(
        _payload(CustomerTier.ENTERPRISE),
        source=LicenseSource.AUTO_FETCH,
        tenant_id=TEST_TENANT_ID,
    )
    metadata = get_cached_license_metadata(tenant_id=TEST_TENANT_ID)
    assert metadata is not None
    assert metadata.customer_tier == CustomerTier.ENTERPRISE
    assert metadata.source == LicenseSource.AUTO_FETCH


def test_legacy_payload_keeps_customer_tier_none_through_cache() -> None:
    """Back-compat: a legacy payload with customer_tier=None survives the
    cache round trip with the field still None. tier_from_license_metadata
    then translates that None to Tier.ENTERPRISE at the resolver layer
    (covered in the unit test for the resolver)."""
    update_license_cache(
        _payload(customer_tier=None),
        source=LicenseSource.MANUAL_UPLOAD,
        tenant_id=TEST_TENANT_ID,
    )
    metadata = get_cached_license_metadata(tenant_id=TEST_TENANT_ID)
    assert metadata is not None
    assert metadata.customer_tier is None
