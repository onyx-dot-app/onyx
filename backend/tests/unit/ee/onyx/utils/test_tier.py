"""Unit tests for `ee.onyx.utils.tier._self_hosted_tier`.

Focuses on cache-failure resilience: a Redis blip on the cached license
read must not bubble up to callers (e.g. admin settings updates).
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from ee.onyx.server.license.models import CustomerTier
from onyx.db.enums import AccessType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Tier


def _metadata(
    customer_tier: CustomerTier | str | None = CustomerTier.ENTERPRISE,
    status: ApplicationStatus = ApplicationStatus.ACTIVE,
) -> MagicMock:
    m = MagicMock()
    m.customer_tier = customer_tier
    m.status = status
    return m


@patch("ee.onyx.utils.tier.MULTI_TENANT", False)
class TestSelfHostedTierCacheFailure:
    """`_self_hosted_tier` must not leak RedisError to callers."""

    @patch("ee.onyx.utils.tier.get_cached_license_metadata")
    def test_cache_hit_returns_cached_tier(self, mock_get_cached: MagicMock) -> None:
        from ee.onyx.utils.tier import get_tier

        mock_get_cached.return_value = _metadata(CustomerTier.ENTERPRISE)
        assert get_tier() == Tier.ENTERPRISE

    @patch("ee.onyx.utils.tier.refresh_license_cache")
    @patch("ee.onyx.utils.tier.get_session_with_current_tenant")
    @patch("ee.onyx.utils.tier.get_cached_license_metadata")
    def test_redis_error_falls_through_to_db(
        self,
        mock_get_cached: MagicMock,
        _mock_session: MagicMock,
        mock_refresh: MagicMock,
    ) -> None:
        """Cache RedisError is treated as a miss; DB resolves the tier."""
        from ee.onyx.utils.tier import get_tier

        mock_get_cached.side_effect = RedisError("redis is down")
        mock_refresh.return_value = _metadata(CustomerTier.BUSINESS)

        assert get_tier() == Tier.BUSINESS
        mock_refresh.assert_called_once()

    @patch("ee.onyx.utils.tier.refresh_license_cache")
    @patch("ee.onyx.utils.tier.get_session_with_current_tenant")
    @patch("ee.onyx.utils.tier.get_cached_license_metadata")
    def test_redis_and_db_both_fail_returns_community(
        self,
        mock_get_cached: MagicMock,
        _mock_session: MagicMock,
        mock_refresh: MagicMock,
    ) -> None:
        """Both backends down: existing SQLAlchemyError block returns COMMUNITY."""
        from ee.onyx.utils.tier import get_tier

        mock_get_cached.side_effect = RedisError("redis is down")
        mock_refresh.side_effect = SQLAlchemyError("db is down")

        assert get_tier() == Tier.COMMUNITY

    @patch("ee.onyx.utils.tier.get_cached_license_metadata")
    def test_non_redis_exception_propagates(self, mock_get_cached: MagicMock) -> None:
        """Except clause stays narrow — unrelated errors still bubble up."""
        from ee.onyx.utils.tier import get_tier

        mock_get_cached.side_effect = ValueError("unexpected")

        with pytest.raises(ValueError, match="unexpected"):
            get_tier()


class TestTierFromLicenseMetadata:
    """All branches of `tier_from_license_metadata` (tier.py:67-83).

    The helper is the single point where license metadata → Tier translation
    happens for self-hosted instances. Covers the back-compat fallback that
    keeps legacy licenses (no `customer_tier` field) and unrecognized future
    tiers working as ENTERPRISE.
    """

    def test_none_metadata_returns_community(self) -> None:
        from ee.onyx.utils.tier import tier_from_license_metadata

        assert tier_from_license_metadata(None) == Tier.COMMUNITY

    def test_gated_access_returns_community_even_with_valid_tier(self) -> None:
        """GATED_ACCESS short-circuits before customer_tier is read."""
        from ee.onyx.utils.tier import tier_from_license_metadata

        m = _metadata(
            customer_tier=CustomerTier.ENTERPRISE,
            status=ApplicationStatus.GATED_ACCESS,
        )
        assert tier_from_license_metadata(m) == Tier.COMMUNITY

    @pytest.mark.parametrize(
        "customer_tier,expected_tier",
        [
            (CustomerTier.BUSINESS, Tier.BUSINESS),
            (CustomerTier.ENTERPRISE, Tier.ENTERPRISE),
            # back-compat: legacy license without customer_tier → ENTERPRISE
            (None, Tier.ENTERPRISE),
            # back-compat: unrecognized future tier value → ENTERPRISE
            ("UNRECOGNIZED_FUTURE_TIER", Tier.ENTERPRISE),
        ],
        ids=[
            "business",
            "enterprise",
            "legacy_none_backcompat",
            "unrecognized_backcompat",
        ],
    )
    def test_resolves_active_metadata(
        self,
        customer_tier: CustomerTier | None | str,
        expected_tier: Tier,
    ) -> None:
        from ee.onyx.utils.tier import tier_from_license_metadata

        m = _metadata(
            customer_tier=customer_tier,
            status=ApplicationStatus.ACTIVE,
        )
        assert tier_from_license_metadata(m) == expected_tier


class TestRequireBusinessTierForSyncAccess:
    """`require_business_tier_for_sync_access` is called from
    `add_credential_to_connector` when a cc-pair is being created with
    `access_type=SYNC`. Below BUSINESS must raise FEATURE_NOT_AVAILABLE;
    non-SYNC access types are unconditional pass-through.
    """

    @pytest.mark.parametrize(
        "access_type",
        [AccessType.PUBLIC, AccessType.PRIVATE],
        ids=["public", "private"],
    )
    @patch("ee.onyx.utils.tier.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.utils.tier.get_tier")
    def test_non_sync_access_passes_without_checking_tier(
        self, mock_get_tier: MagicMock, access_type: AccessType
    ) -> None:
        from ee.onyx.utils.tier import require_business_tier_for_sync_access

        require_business_tier_for_sync_access(access_type)
        mock_get_tier.assert_not_called()

    @patch("ee.onyx.utils.tier.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.utils.tier.get_tier")
    def test_sync_at_community_raises_feature_not_available(
        self, mock_get_tier: MagicMock
    ) -> None:
        from ee.onyx.utils.tier import require_business_tier_for_sync_access

        mock_get_tier.return_value = Tier.COMMUNITY
        with pytest.raises(OnyxError) as exc_info:
            require_business_tier_for_sync_access(AccessType.SYNC)
        assert exc_info.value.error_code == OnyxErrorCode.FEATURE_NOT_AVAILABLE

    @pytest.mark.parametrize(
        "tier",
        [Tier.BUSINESS, Tier.ENTERPRISE],
        ids=["business", "enterprise"],
    )
    @patch("ee.onyx.utils.tier.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.utils.tier.get_tier")
    def test_sync_at_business_or_enterprise_passes(
        self, mock_get_tier: MagicMock, tier: Tier
    ) -> None:
        from ee.onyx.utils.tier import require_business_tier_for_sync_access

        mock_get_tier.return_value = tier
        require_business_tier_for_sync_access(AccessType.SYNC)

    @patch("ee.onyx.utils.tier.LICENSE_ENFORCEMENT_ENABLED", False)
    @patch("ee.onyx.utils.tier.get_tier")
    def test_legacy_enforcement_disabled_passes_without_checking_tier(
        self, mock_get_tier: MagicMock
    ) -> None:
        """EE deployment with LICENSE_ENFORCEMENT_ENABLED=False — treat as
        ENTERPRISE, same as `apply_license_status_to_settings`. Don't
        block legacy installs that never loaded a license."""
        from ee.onyx.utils.tier import require_business_tier_for_sync_access

        require_business_tier_for_sync_access(AccessType.SYNC)
        mock_get_tier.assert_not_called()
