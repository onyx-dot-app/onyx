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
