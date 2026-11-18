"""Tests for product gating functions."""

from unittest.mock import MagicMock, patch

import pytest


class TestIsTenantGated:
    """Tests for is_tenant_gated - the O(1) cache check used by middleware."""

    @pytest.mark.parametrize(
        "redis_result,expected",
        [
            (True, True),
            (False, False),
        ],
    )
    @patch("ee.onyx.server.tenants.product_gating.get_cache_backend")
    def test_tenant_gated_status(
        self,
        mock_get_redis: MagicMock,
        redis_result: bool,
        expected: bool,
    ) -> None:
        """is_tenant_gated reads the gated set from the replica."""
        from ee.onyx.server.tenants.product_gating import is_tenant_gated

        mock_redis = MagicMock()
        mock_redis.set_contains.return_value = redis_result
        mock_get_redis.return_value = mock_redis

        assert is_tenant_gated("test_tenant") is expected
        assert mock_get_redis.call_args.kwargs["replica"] is True


class TestUpdateTenantGating:
    """Tests for update_tenant_gating - modifies the gated set."""

    @pytest.mark.parametrize(
        "status,should_add_to_set",
        [
            ("gated_access", True),  # Only GATED_ACCESS adds to set
            ("active", False),  # All other statuses remove from set
        ],
    )
    @patch("ee.onyx.server.tenants.product_gating.get_cache_backend")
    def test_gating_set_modification(
        self,
        mock_get_redis: MagicMock,
        status: str,
        should_add_to_set: bool,
    ) -> None:
        """update_tenant_gating adds tenant to set only for GATED_ACCESS status."""
        from ee.onyx.server.tenants.product_gating import update_tenant_gating
        from onyx.server.settings.models import ApplicationStatus

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        update_tenant_gating("test_tenant", ApplicationStatus(status))

        if should_add_to_set:
            mock_redis.set_add.assert_called_once()
            mock_redis.set_remove.assert_not_called()
        else:
            mock_redis.set_remove.assert_called_once()
            mock_redis.set_add.assert_not_called()
