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
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Tier


def _metadata(
    customer_tier: CustomerTier | None = CustomerTier.ENTERPRISE,
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
        ids=["business", "enterprise", "legacy_none_backcompat", "unrecognized_backcompat"],
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
