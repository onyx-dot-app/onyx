"""Unit tests for Teams bot cache manager."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.onyxbot.teams.cache import TeamsCacheManager


class TestCacheInitialization:
    """Tests for cache initialization."""

    def test_cache_starts_empty(self) -> None:
        cache = TeamsCacheManager()
        assert cache._entity_tenants == {}
        assert cache._api_keys == {}
        assert cache.is_initialized is False

    @pytest.mark.asyncio
    async def test_cache_refresh_all_loads_teams(self) -> None:
        cache = TeamsCacheManager()

        mock_config1 = MagicMock()
        mock_config1.team_id = "team-111"
        mock_config1.enabled = True

        mock_config2 = MagicMock()
        mock_config2.team_id = "team-222"
        mock_config2.enabled = True

        with (
            patch(
                "onyx.onyxbot.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.teams.cache.get_team_configs",
                return_value=[mock_config1, mock_config2],
            ),
            patch(
                "onyx.onyxbot.teams.cache.get_or_create_teams_service_api_key",
                return_value="test_api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        assert cache.is_initialized is True
        assert "team-111" in cache._entity_tenants
        assert "team-222" in cache._entity_tenants
        assert cache._entity_tenants["team-111"] == "tenant1"

    @pytest.mark.asyncio
    async def test_cache_refresh_provisions_api_key(self) -> None:
        cache = TeamsCacheManager()

        mock_config = MagicMock()
        mock_config.team_id = "team-111"
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.teams.cache.get_team_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.teams.cache.get_or_create_teams_service_api_key",
                return_value="new_api_key",
            ) as mock_provision,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        assert cache._api_keys.get("tenant1") == "new_api_key"
        mock_provision.assert_called()


class TestCacheLookups:
    """Tests for cache lookup operations."""

    def test_get_tenant_returns_correct(self) -> None:
        cache = TeamsCacheManager()
        cache._entity_tenants["team-123"] = "tenant1"
        assert cache.get_tenant("team-123") == "tenant1"

    def test_get_tenant_returns_none_unknown(self) -> None:
        cache = TeamsCacheManager()
        assert cache.get_tenant("unknown-team") is None

    def test_get_api_key_returns_correct(self) -> None:
        cache = TeamsCacheManager()
        cache._api_keys["tenant1"] = "api_key_123"
        assert cache.get_api_key("tenant1") == "api_key_123"

    def test_get_api_key_returns_none_unknown(self) -> None:
        cache = TeamsCacheManager()
        assert cache.get_api_key("unknown_tenant") is None

    def test_get_all_team_ids(self) -> None:
        cache = TeamsCacheManager()
        cache._entity_tenants = {"t1": "tenant1", "t2": "tenant2", "t3": "tenant1"}
        result = cache.get_all_team_ids()
        assert set(result) == {"t1", "t2", "t3"}


class TestCacheUpdates:
    """Tests for cache update operations."""

    @pytest.mark.asyncio
    async def test_refresh_team_adds_new(self) -> None:
        cache = TeamsCacheManager()

        mock_config = MagicMock()
        mock_config.team_id = "team-111"
        mock_config.enabled = True

        with (
            patch("onyx.onyxbot.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.teams.cache.get_team_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.teams.cache.get_or_create_teams_service_api_key",
                return_value="api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_team("team-111", "tenant1")

        assert cache.get_tenant("team-111") == "tenant1"

    def test_remove_team(self) -> None:
        cache = TeamsCacheManager()
        cache._entity_tenants["team-111"] = "tenant1"
        cache.remove_team("team-111")
        assert cache.get_tenant("team-111") is None

    def test_clear_removes_all(self) -> None:
        cache = TeamsCacheManager()
        cache._entity_tenants = {"t1": "tenant1", "t2": "tenant2"}
        cache._api_keys = {"tenant1": "key1", "tenant2": "key2"}
        cache._initialized = True

        cache.clear()

        assert cache._entity_tenants == {}
        assert cache._api_keys == {}
        assert cache.is_initialized is False


class TestGatedTenantHandling:
    """Tests for gated tenant filtering."""

    @pytest.mark.asyncio
    async def test_refresh_skips_gated_tenants(self) -> None:
        cache = TeamsCacheManager()
        gated_tenants = {"tenant2"}

        mock_config = MagicMock()
        mock_config.team_id = "team-111"
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.cache.get_all_tenant_ids",
                return_value=["tenant1", "tenant2"],
            ),
            patch(
                "onyx.onyxbot.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: gated_tenants,
            ),
            patch("onyx.onyxbot.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.teams.cache.get_team_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.teams.cache.get_or_create_teams_service_api_key",
                return_value="api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        assert "tenant1" in cache._api_keys
        assert "tenant2" not in cache._api_keys
