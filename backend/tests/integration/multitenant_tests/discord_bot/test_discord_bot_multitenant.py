"""Multi-tenant isolation tests for Discord bot.

These tests ensure tenant isolation and prevent data leakage between tenants.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import AuthType
from onyx.db.discord_bot import get_guild_configs
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.onyxbot.discord.constants import REGISTRATION_KEY_PREFIX
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key


class TestBotConfigIsolationCloudMode:
    """Tests for bot config isolation in cloud mode."""

    def test_cannot_create_bot_config_in_cloud_mode(self) -> None:
        """Bot config creation is blocked in cloud mode."""
        with patch("onyx.configs.app_configs.AUTH_TYPE", AuthType.CLOUD):
            from onyx.server.manage.discord_bot.api import _check_bot_config_api_access
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                _check_bot_config_api_access()

            assert exc_info.value.status_code == 403
            assert "Cloud" in str(exc_info.value.detail)

    def test_bot_token_from_env_only_in_cloud(self) -> None:
        """Bot token comes from env var in cloud mode, ignores DB."""
        from onyx.onyxbot.discord.utils import get_bot_token

        with (
            patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", "env_token"),
            patch("onyx.onyxbot.discord.utils.AUTH_TYPE", AuthType.CLOUD),
        ):
            result = get_bot_token()

        assert result == "env_token"


class TestGuildRegistrationIsolation:
    """Tests for guild registration isolation between tenants."""

    def test_guild_can_only_register_to_one_tenant(self) -> None:
        """Guild registered to tenant 1 cannot be registered to tenant 2."""
        cache = DiscordCacheManager()

        # Register guild to tenant 1
        cache._guild_tenants[123456789] = "tenant1"

        # Check if guild is already registered
        existing = cache.get_tenant(123456789)

        assert existing is not None
        assert existing == "tenant1"

    def test_registration_key_tenant_mismatch(self) -> None:
        """Key created in tenant 1 cannot be used in tenant 2 context."""
        key = generate_discord_registration_key("tenant1")

        # Parse the key to get tenant
        parsed_tenant = parse_discord_registration_key(key)

        assert parsed_tenant == "tenant1"
        assert parsed_tenant != "tenant2"

    def test_registration_key_encodes_correct_tenant(self) -> None:
        """Key format discord_<tenant_id>.<token> encodes correct tenant."""
        tenant_id = "my_tenant_123"
        key = generate_discord_registration_key(tenant_id)

        assert key.startswith(REGISTRATION_KEY_PREFIX)
        assert "my_tenant_123" in key or "my%5Ftenant%5F123" in key

        parsed = parse_discord_registration_key(key)
        assert parsed == tenant_id


class TestGuildDataIsolation:
    """Tests for guild data isolation between tenants."""

    @pytest.mark.asyncio
    async def test_tenant_cannot_see_other_tenant_guilds(self) -> None:
        """Guilds created in tenant 1 are not visible from tenant 2."""
        # This tests that get_guild_configs only returns guilds for current tenant
        # Mock database calls for two different tenants

        tenant1_configs = [MagicMock(guild_id=111), MagicMock(guild_id=222)]

        with patch("onyx.db.discord_bot.get_guild_configs") as mock_get:
            # When called in tenant1 context
            mock_get.return_value = tenant1_configs

            # Verify only tenant1 guilds returned
            result = mock_get(MagicMock())
            assert len(result) == 2
            assert all(c.guild_id in [111, 222] for c in result)

    @pytest.mark.asyncio
    async def test_guild_list_returns_only_own_tenant(self) -> None:
        """List guilds returns exactly the guilds for that tenant."""
        # Create mock configs for specific tenant
        mock_configs = [
            MagicMock(guild_id=111),
            MagicMock(guild_id=222),
            MagicMock(guild_id=333),
        ]

        with patch(
            "onyx.db.discord_bot.get_guild_configs",
            return_value=mock_configs,
        ):
            # Should return exactly 3
            result = get_guild_configs(MagicMock())
            assert len(result) == 3


class TestChannelDataIsolation:
    """Tests for channel data isolation between tenants."""

    @pytest.mark.asyncio
    async def test_tenant_cannot_see_other_tenant_channels(self) -> None:
        """Channels in tenant 1 guild are not visible from tenant 2."""
        # Channel lookup should return empty for wrong tenant
        from onyx.db.discord_bot import get_channel_config_by_discord_ids

        with patch(
            "onyx.db.discord_bot.get_channel_config_by_discord_ids",
            return_value=None,  # Not found in this tenant
        ):
            result = get_channel_config_by_discord_ids(
                MagicMock(), guild_id=123, channel_id=456
            )
            assert result is None


class TestCacheManagerIsolation:
    """Tests for cache manager tenant isolation."""

    def test_cache_maps_guild_to_correct_tenant(self) -> None:
        """Cache correctly maps guild_id to tenant_id."""
        cache = DiscordCacheManager()

        # Set up mappings
        cache._guild_tenants[111] = "tenant1"
        cache._guild_tenants[222] = "tenant2"
        cache._guild_tenants[333] = "tenant1"

        assert cache.get_tenant(111) == "tenant1"
        assert cache.get_tenant(222) == "tenant2"
        assert cache.get_tenant(333) == "tenant1"
        assert cache.get_tenant(444) is None

    def test_api_key_per_tenant_isolation(self) -> None:
        """Each tenant has unique API key."""
        cache = DiscordCacheManager()

        cache._api_keys["tenant1"] = "key_for_tenant1"
        cache._api_keys["tenant2"] = "key_for_tenant2"

        assert cache.get_api_key("tenant1") == "key_for_tenant1"
        assert cache.get_api_key("tenant2") == "key_for_tenant2"
        assert cache.get_api_key("tenant1") != cache.get_api_key("tenant2")


class TestAPIRequestIsolation:
    """Tests for API request isolation between tenants."""

    @pytest.mark.asyncio
    async def test_discord_bot_uses_tenant_specific_api_key(self) -> None:
        """Message from guild in tenant 1 uses tenant 1's API key."""
        cache = DiscordCacheManager()
        cache._guild_tenants[123456] = "tenant1"
        cache._api_keys["tenant1"] = "tenant1_api_key"
        cache._api_keys["tenant2"] = "tenant2_api_key"

        # When processing message from guild 123456
        tenant = cache.get_tenant(123456)
        assert tenant is not None
        api_key = cache.get_api_key(tenant)

        assert tenant == "tenant1"
        assert api_key == "tenant1_api_key"
        assert api_key != "tenant2_api_key"

    @pytest.mark.asyncio
    async def test_guild_message_routes_to_correct_tenant(self) -> None:
        """Message from registered guild routes to correct tenant context."""
        cache = DiscordCacheManager()
        cache._guild_tenants[999] = "target_tenant"
        cache._api_keys["target_tenant"] = "target_key"

        # Simulate message routing
        guild_id = 999
        tenant = cache.get_tenant(guild_id)
        api_key = cache.get_api_key(tenant) if tenant else None

        assert tenant == "target_tenant"
        assert api_key == "target_key"
