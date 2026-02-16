"""Tests for product gating functions."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


class TestIsTenantGated:
    """Tests for is_tenant_gated - the O(1) Redis check used by middleware."""

    @pytest.mark.parametrize(
        "redis_result,expected",
        [
            (True, True),
            (False, False),
            (1, True),  # Redis sismember can return int
            (0, False),
        ],
    )
    @patch("ee.onyx.server.tenants.product_gating.get_redis_replica_client")
    def test_tenant_gated_status(
        self,
        mock_get_redis: MagicMock,
        redis_result: bool | int,
        expected: bool,
    ) -> None:
        """is_tenant_gated correctly interprets Redis sismember result."""
        from ee.onyx.server.tenants.product_gating import is_tenant_gated

        mock_redis = MagicMock()
        mock_redis.sismember.return_value = redis_result
        mock_get_redis.return_value = mock_redis

        assert is_tenant_gated("test_tenant") is expected


class TestUpdateTenantGating:
    """Tests for update_tenant_gating - modifies Redis gated set."""

    @pytest.mark.parametrize(
        "status,should_add_to_set",
        [
            ("gated_access", True),  # Only GATED_ACCESS adds to set
            ("active", False),  # All other statuses remove from set
        ],
    )
    @patch("ee.onyx.server.tenants.product_gating.get_redis_client")
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
            mock_redis.sadd.assert_called_once()
            mock_redis.srem.assert_not_called()
        else:
            mock_redis.srem.assert_called_once()
            mock_redis.sadd.assert_not_called()
