"""Unit tests for Discord bot cache manager.

Tests for DiscordCacheManager class functionality.
"""

import asyncio
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.onyxbot.discord.cache import DiscordCacheManager


class TestCacheInitialization:
    """Tests for cache initialization."""

    def test_cache_starts_empty(self) -> None:
        """New cache manager has empty caches."""
        cache = DiscordCacheManager()
        assert cache._guild_tenants == {}
        assert cache._api_keys == {}
        assert cache.is_initialized is False

    @pytest.mark.asyncio
    async def test_cache_refresh_all_loads_guilds(self) -> None:
        """refresh_all() loads all active guilds."""
        cache = DiscordCacheManager()

        mock_config1 = MagicMock()
        mock_config1.guild_id = 111111
        mock_config1.enabled = True

        mock_config2 = MagicMock()
        mock_config2.guild_id = 222222
        mock_config2.enabled = True

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config1, mock_config2],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
                return_value="test_api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        assert cache.is_initialized is True
        assert 111111 in cache._guild_tenants
        assert 222222 in cache._guild_tenants
        assert cache._guild_tenants[111111] == "tenant1"
        assert cache._guild_tenants[222222] == "tenant1"

    @pytest.mark.asyncio
    async def test_cache_refresh_provisions_api_key(self) -> None:
        """Refresh for tenant without key creates API key."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
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
        """Lookup registered guild returns correct tenant ID."""
        cache = DiscordCacheManager()
        cache._guild_tenants[123456] = "tenant1"

        result = cache.get_tenant(123456)
        assert result == "tenant1"

    def test_get_tenant_returns_none_unknown(self) -> None:
        """Lookup unregistered guild returns None."""
        cache = DiscordCacheManager()

        result = cache.get_tenant(999999)
        assert result is None

    def test_get_api_key_returns_correct(self) -> None:
        """Lookup tenant's API key returns valid key."""
        cache = DiscordCacheManager()
        cache._api_keys["tenant1"] = "api_key_123"

        result = cache.get_api_key("tenant1")
        assert result == "api_key_123"

    def test_get_api_key_returns_none_unknown(self) -> None:
        """Lookup unknown tenant returns None."""
        cache = DiscordCacheManager()

        result = cache.get_api_key("unknown_tenant")
        assert result is None

    def test_get_all_guild_ids(self) -> None:
        """After loading returns all cached guild IDs."""
        cache = DiscordCacheManager()
        cache._guild_tenants = {111: "t1", 222: "t2", 333: "t1"}

        result = cache.get_all_guild_ids()
        assert set(result) == {111, 222, 333}


class TestCacheUpdates:
    """Tests for cache update operations."""

    @pytest.mark.asyncio
    async def test_refresh_guild_adds_new(self) -> None:
        """refresh_guild() for new guild adds it to cache."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        with (
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
                return_value="api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_guild(111111, "tenant1")

        assert cache.get_tenant(111111) == "tenant1"

    @pytest.mark.asyncio
    async def test_refresh_guild_verifies_active(self) -> None:
        """refresh_guild() for disabled guild doesn't add it."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = False  # Disabled!

        with (
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_guild(111111, "tenant1")

        # Should not be added because it's disabled
        assert cache.get_tenant(111111) is None

    def test_remove_guild(self) -> None:
        """remove_guild() removes guild from cache."""
        cache = DiscordCacheManager()
        cache._guild_tenants[111111] = "tenant1"

        cache.remove_guild(111111)

        assert cache.get_tenant(111111) is None

    def test_clear_removes_all(self) -> None:
        """clear() empties all caches."""
        cache = DiscordCacheManager()
        cache._guild_tenants = {111: "t1", 222: "t2"}
        cache._api_keys = {"t1": "key1", "t2": "key2"}
        cache._initialized = True

        cache.clear()

        assert cache._guild_tenants == {}
        assert cache._api_keys == {}
        assert cache.is_initialized is False


class TestThreadSafety:
    """Tests for thread/async safety."""

    @pytest.mark.asyncio
    async def test_concurrent_refresh_no_race(self) -> None:
        """Multiple concurrent refresh_all() calls don't corrupt data."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        call_count = 0

        async def slow_refresh() -> tuple[list[int], str]:
            nonlocal call_count
            call_count += 1
            # Simulate slow operation
            await asyncio.sleep(0.01)
            return ([111111], "api_key")

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch.object(cache, "_load_tenant_data", side_effect=slow_refresh),
        ):
            # Run multiple concurrent refreshes
            await asyncio.gather(
                cache.refresh_all(),
                cache.refresh_all(),
                cache.refresh_all(),
            )

        # Each refresh should complete without error
        assert cache.is_initialized is True

    @pytest.mark.asyncio
    async def test_concurrent_read_write(self) -> None:
        """Read during refresh doesn't cause exceptions."""
        cache = DiscordCacheManager()
        cache._guild_tenants[111111] = "tenant1"

        async def read_loop() -> None:
            for _ in range(10):
                cache.get_tenant(111111)
                await asyncio.sleep(0.001)

        async def write_loop() -> None:
            for i in range(10):
                cache._guild_tenants[200000 + i] = f"tenant{i}"
                await asyncio.sleep(0.001)

        # Should not raise any exceptions
        await asyncio.gather(read_loop(), write_loop())


class TestAPIKeyProvisioning:
    """Tests for API key provisioning via cache refresh."""

    @pytest.mark.asyncio
    async def test_api_key_created_on_first_refresh(self) -> None:
        """Cache refresh with no existing key creates new API key."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
                return_value="new_api_key_123",
            ) as mock_create,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        mock_create.assert_called_once()
        assert cache.get_api_key("tenant1") == "new_api_key_123"

    @pytest.mark.asyncio
    async def test_api_key_cached_after_creation(self) -> None:
        """Subsequent lookups after creation use cached key."""
        cache = DiscordCacheManager()
        cache._api_keys["tenant1"] = "cached_key"

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
            ) as mock_create,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        # Should NOT call create because key is already cached
        mock_create.assert_not_called()
        # Cached key should be preserved after refresh
        assert cache.get_api_key("tenant1") == "cached_key"


class TestGatedTenantHandling:
    """Tests for gated tenant filtering."""

    @pytest.mark.asyncio
    async def test_refresh_skips_gated_tenants(self) -> None:
        """Gated tenant's guilds are not loaded."""
        cache = DiscordCacheManager()

        # tenant2 is gated
        gated_tenants = {"tenant2"}

        mock_config_t1 = MagicMock()
        mock_config_t1.guild_id = 111111
        mock_config_t1.enabled = True

        mock_config_t2 = MagicMock()
        mock_config_t2.guild_id = 222222
        mock_config_t2.enabled = True

        def mock_get_configs(db: MagicMock) -> list[MagicMock]:
            # Track which tenant this was called for
            return [mock_config_t1]  # Always return same for simplicity

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1", "tenant2"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: gated_tenants,
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                side_effect=mock_get_configs,
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
                return_value="api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        # Only tenant1 should be loaded (tenant2 is gated)
        assert "tenant1" in cache._api_keys and 111111 in cache._guild_tenants
        # tenant2's guilds should NOT be in cache
        assert "tenant2" not in cache._api_keys and 222222 not in cache._guild_tenants

    @pytest.mark.asyncio
    async def test_gated_check_calls_ee_function(self) -> None:
        """Refresh all tenants calls fetch_ee_implementation_or_noop."""
        cache = DiscordCacheManager()

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ) as mock_ee,
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[],
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        mock_ee.assert_called_once()

    @pytest.mark.asyncio
    async def test_ungated_tenant_included(self) -> None:
        """Regular (ungated) tenant has guilds loaded normally."""
        cache = DiscordCacheManager()

        mock_config = MagicMock()
        mock_config.guild_id = 111111
        mock_config.enabled = True

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),  # No gated tenants
            ),
            patch("onyx.onyxbot.discord.cache.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.cache.get_guild_configs",
                return_value=[mock_config],
            ),
            patch(
                "onyx.onyxbot.discord.cache.get_or_create_discord_service_api_key",
                return_value="api_key",
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            await cache.refresh_all()

        assert cache.get_tenant(111111) == "tenant1"


class TestCacheErrorHandling:
    """Tests for error handling in cache operations."""

    @pytest.mark.asyncio
    async def test_refresh_all_handles_tenant_error(self) -> None:
        """Error loading one tenant doesn't stop others."""
        cache = DiscordCacheManager()

        call_count = 0

        async def mock_load(tenant_id: str) -> tuple[list[int], str]:
            nonlocal call_count
            call_count += 1
            if tenant_id == "tenant1":
                raise Exception("Tenant 1 error")
            return ([222222], "api_key")

        with (
            patch(
                "onyx.onyxbot.discord.cache.get_all_tenant_ids",
                return_value=["tenant1", "tenant2"],
            ),
            patch(
                "onyx.onyxbot.discord.cache.fetch_ee_implementation_or_noop",
                return_value=lambda: set(),
            ),
            patch.object(cache, "_load_tenant_data", side_effect=mock_load),
        ):
            await cache.refresh_all()

        # Should still complete and load tenant2
        assert call_count == 2  # Both tenants attempted
        assert cache.get_tenant(222222) == "tenant2"
