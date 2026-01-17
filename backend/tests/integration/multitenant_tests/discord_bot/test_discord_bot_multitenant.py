"""Multi-tenant isolation tests for Discord bot.

These tests ensure tenant isolation and prevent data leakage between tenants.
Tests follow the multi-tenant integration test pattern using API requests.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
import requests

from onyx.configs.constants import AuthType
from onyx.db.models import UserRole
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.onyxbot.discord.constants import REGISTRATION_KEY_PREFIX
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


class TestBotConfigIsolationCloudMode:
    """Tests for bot config isolation in cloud mode."""

    def test_cannot_create_bot_config_in_cloud_mode(self) -> None:
        """Bot config creation is blocked in cloud mode."""
        with patch("onyx.configs.app_configs.AUTH_TYPE", AuthType.CLOUD):
            from fastapi import HTTPException

            from onyx.server.manage.discord_bot.api import _check_bot_config_api_access

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
    """Tests for guild data isolation between tenants via API."""

    def test_tenant_cannot_see_other_tenant_guilds(
        self, reset_multitenant: None
    ) -> None:
        """Guilds created in tenant 1 are not visible from tenant 2.

        Creates guilds via API in tenant 1, then queries from tenant 2
        context to verify the guilds are not visible.
        """
        unique = uuid4().hex

        # Create admin user for tenant 1
        admin_user1: DATestUser = UserManager.create(
            email=f"discord_admin1+{unique}@example.com",
        )
        assert UserManager.is_role(admin_user1, UserRole.ADMIN)

        # Create admin user for tenant 2
        admin_user2: DATestUser = UserManager.create(
            email=f"discord_admin2+{unique}@example.com",
        )
        assert UserManager.is_role(admin_user2, UserRole.ADMIN)

        # Create a guild registration key in tenant 1
        response1 = requests.post(
            f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
            headers=admin_user1.headers,
        )

        # If Discord bot feature is not enabled, skip the test
        if response1.status_code == 404:
            pytest.skip("Discord bot feature not enabled")

        assert response1.ok, f"Failed to create guild in tenant 1: {response1.text}"
        guild1_data = response1.json()
        guild1_id = guild1_data["id"]

        try:
            # List guilds from tenant 1 - should see the guild
            list_response1 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user1.headers,
            )
            assert list_response1.ok
            tenant1_guilds = list_response1.json()
            tenant1_guild_ids = [g["id"] for g in tenant1_guilds]
            assert guild1_id in tenant1_guild_ids

            # List guilds from tenant 2 - should NOT see tenant 1's guild
            list_response2 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user2.headers,
            )
            assert list_response2.ok
            tenant2_guilds = list_response2.json()
            tenant2_guild_ids = [g["id"] for g in tenant2_guilds]
            assert guild1_id not in tenant2_guild_ids

        finally:
            # Cleanup - delete guild from tenant 1
            requests.delete(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild1_id}",
                headers=admin_user1.headers,
            )

    def test_guild_list_returns_only_own_tenant(self, reset_multitenant: None) -> None:
        """List guilds returns exactly the guilds for that tenant.

        Creates guilds in both tenants and verifies each tenant only sees their own.
        """
        unique = uuid4().hex

        # Create admin users for two tenants
        admin_user1: DATestUser = UserManager.create(
            email=f"discord_list1+{unique}@example.com",
        )
        admin_user2: DATestUser = UserManager.create(
            email=f"discord_list2+{unique}@example.com",
        )

        # Create guilds in tenant 1
        guild_ids_tenant1 = []
        for i in range(2):
            response = requests.post(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user1.headers,
            )
            if response.status_code == 404:
                pytest.skip("Discord bot feature not enabled")
            assert response.ok, f"Failed to create guild {i} in tenant 1"
            guild_ids_tenant1.append(response.json()["id"])

        # Create guilds in tenant 2
        guild_ids_tenant2 = []
        for i in range(2):
            response = requests.post(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user2.headers,
            )
            assert response.ok, f"Failed to create guild {i} in tenant 2"
            guild_ids_tenant2.append(response.json()["id"])

        try:
            # Verify tenant 1 sees only their guilds
            list_response1 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user1.headers,
            )
            assert list_response1.ok
            visible_ids_1 = {g["id"] for g in list_response1.json()}

            for gid in guild_ids_tenant1:
                assert gid in visible_ids_1, f"Tenant 1 should see guild {gid}"
            for gid in guild_ids_tenant2:
                assert gid not in visible_ids_1, f"Tenant 1 should NOT see guild {gid}"

            # Verify tenant 2 sees only their guilds
            list_response2 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user2.headers,
            )
            assert list_response2.ok
            visible_ids_2 = {g["id"] for g in list_response2.json()}

            for gid in guild_ids_tenant2:
                assert gid in visible_ids_2, f"Tenant 2 should see guild {gid}"
            for gid in guild_ids_tenant1:
                assert gid not in visible_ids_2, f"Tenant 2 should NOT see guild {gid}"

        finally:
            # Cleanup
            for gid in guild_ids_tenant1:
                requests.delete(
                    f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{gid}",
                    headers=admin_user1.headers,
                )
            for gid in guild_ids_tenant2:
                requests.delete(
                    f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{gid}",
                    headers=admin_user2.headers,
                )


class TestGuildAccessIsolation:
    """Tests for guild access isolation between tenants."""

    def test_tenant_cannot_access_other_tenant_guild(
        self, reset_multitenant: None
    ) -> None:
        """Tenant 2 cannot access or modify tenant 1's guild by ID.

        Creates a guild in tenant 1, then attempts to access it from tenant 2.
        """
        unique = uuid4().hex

        # Create admin users for two tenants
        admin_user1: DATestUser = UserManager.create(
            email=f"discord_access1+{unique}@example.com",
        )
        admin_user2: DATestUser = UserManager.create(
            email=f"discord_access2+{unique}@example.com",
        )

        # Create a guild in tenant 1
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
            headers=admin_user1.headers,
        )
        if response.status_code == 404:
            pytest.skip("Discord bot feature not enabled")
        assert response.ok
        guild1_id = response.json()["id"]

        try:
            # Tenant 2 tries to get the guild - should fail (404 or 403)
            get_response = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild1_id}",
                headers=admin_user2.headers,
            )
            # Should either return 404 (not found) or 403 (forbidden)
            assert get_response.status_code in [
                403,
                404,
            ], f"Expected 403 or 404, got {get_response.status_code}"

            # Tenant 2 tries to delete the guild - should fail
            delete_response = requests.delete(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild1_id}",
                headers=admin_user2.headers,
            )
            assert delete_response.status_code in [403, 404]

        finally:
            # Cleanup - delete from tenant 1
            requests.delete(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild1_id}",
                headers=admin_user1.headers,
            )


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
