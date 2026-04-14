"""Unit tests for tenant host mapping / routing logic.

These tests mock Redis and the control plane — no external services required.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.engine.tenant_host_mapping import _lru_get_host_index
from onyx.db.engine.tenant_host_mapping import compute_host_index
from onyx.db.engine.tenant_host_mapping import get_host_index_for_tenant
from onyx.db.engine.tenant_host_mapping import get_host_index_from_redis
from onyx.db.engine.tenant_host_mapping import REDIS_TENANT_HOST_KEY_PREFIX


# ── compute_host_index ─────────────────────────────────────────────


class TestComputeHostIndex:
    """Tests for the pure cutoff-bisect function."""

    def setup_method(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None

    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS", [])
    def test_no_cutoffs_always_zero(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        assert compute_host_index(datetime(2020, 1, 1, tzinfo=timezone.utc)) == 0
        assert compute_host_index(datetime(2099, 1, 1, tzinfo=timezone.utc)) == 0

    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_single_cutoff_before(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        dt = datetime(2026, 3, 15, tzinfo=timezone.utc)
        assert compute_host_index(dt) == 0

    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_single_cutoff_after(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        dt = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert compute_host_index(dt) == 1

    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_single_cutoff_exact_boundary(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        dt = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        # bisect_right: equal goes right → host 1
        assert compute_host_index(dt) == 1

    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"],
    )
    def test_two_cutoffs_middle(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        assert compute_host_index(datetime(2025, 6, 1, tzinfo=timezone.utc)) == 0
        assert compute_host_index(datetime(2026, 3, 1, tzinfo=timezone.utc)) == 1
        assert compute_host_index(datetime(2026, 9, 1, tzinfo=timezone.utc)) == 2

    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_naive_datetime_treated_as_utc(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        dt = datetime(2026, 3, 15)
        assert compute_host_index(dt) == 0


# ── get_host_index_for_tenant ──────────────────────────────────────


class TestGetHostIndexForTenant:
    """Tests for the full resolution chain: LRU → Redis → CP."""

    def setup_method(self) -> None:
        _lru_get_host_index.cache_clear()

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", False)
    def test_single_tenant_always_zero(self) -> None:
        assert get_host_index_for_tenant("public") == 0

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0"])
    def test_single_host_always_zero(self) -> None:
        assert get_host_index_for_tenant("tenant_abc") == 0

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0", "host1"])
    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_redis_hit(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        _lru_get_host_index.cache_clear()

        mock_redis = MagicMock()
        mock_redis.get.return_value = b"1"

        with patch(
            "onyx.redis.redis_pool.get_raw_redis_client",
            return_value=mock_redis,
        ):
            assert get_host_index_for_tenant("tenant_123") == 1
            mock_redis.get.assert_called_once_with(
                f"{REDIS_TENANT_HOST_KEY_PREFIX}tenant_123"
            )

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0", "host1"])
    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_redis_miss_calls_cp(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        _lru_get_host_index.cache_clear()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        cp_created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with (
            patch(
                "onyx.redis.redis_pool.get_raw_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "onyx.db.engine.tenant_host_mapping._fetch_created_at_from_control_plane",
                return_value=cp_created_at,
            ),
        ):
            result = get_host_index_for_tenant("tenant_new")
            assert result == 1

            mock_redis.set.assert_called_once_with(
                f"{REDIS_TENANT_HOST_KEY_PREFIX}tenant_new", "1"
            )

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0", "host1"])
    @patch(
        "onyx.db.engine.tenant_host_mapping.POSTGRES_HOST_CUTOFFS",
        ["2026-04-01T00:00:00Z"],
    )
    def test_cp_unreachable_raises(self) -> None:
        import onyx.db.engine.tenant_host_mapping as mod

        mod._PARSED_CUTOFFS = None
        _lru_get_host_index.cache_clear()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with (
            patch(
                "onyx.redis.redis_pool.get_raw_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "onyx.db.engine.tenant_host_mapping._fetch_created_at_from_control_plane",
                side_effect=Exception("CP down"),
            ),
        ):
            with pytest.raises(Exception, match="CP down"):
                get_host_index_for_tenant("tenant_unreachable")


# ── get_host_index_from_redis ─────────────────────────────────────


class TestGetHostIndexFromRedis:
    """Tests for the Redis-only lookup (no CP fallback)."""

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", False)
    def test_single_tenant_returns_zero(self) -> None:
        assert get_host_index_from_redis("anything") == 0

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0"])
    def test_single_host_returns_zero(self) -> None:
        assert get_host_index_from_redis("tenant_x") == 0

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0", "host1"])
    def test_redis_hit_returns_value(self) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"1"
        with patch(
            "onyx.redis.redis_pool.get_raw_redis_client",
            return_value=mock_redis,
        ):
            assert get_host_index_from_redis("tenant_pool") == 1

    @patch("onyx.db.engine.tenant_host_mapping.MULTI_TENANT", True)
    @patch("onyx.db.engine.tenant_host_mapping.POSTGRES_HOSTS", ["host0", "host1"])
    def test_redis_miss_returns_none(self) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        with patch(
            "onyx.redis.redis_pool.get_raw_redis_client",
            return_value=mock_redis,
        ):
            assert get_host_index_from_redis("tenant_unknown") is None
