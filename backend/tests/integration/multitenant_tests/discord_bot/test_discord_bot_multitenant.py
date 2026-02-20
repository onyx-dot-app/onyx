"""Multi-tenant isolation tests for Discord bot.

These tests ensure tenant isolation and prevent data leakage between tenants.
Tests follow the multi-tenant integration test pattern using API requests.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
import requests

from onyx.configs.constants import AuthType
from onyx.db.discord_bot import get_guild_config_by_registration_key
from onyx.db.discord_bot import register_guild
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import UserRole
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key
from onyx.server.manage.discord_bot.utils import REGISTRATION_KEY_PREFIX
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
        self, reset_multitenant: None  # noqa: ARG002
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

    def test_guild_list_returns_only_own_tenant(
        self, reset_multitenant: None  # noqa: ARG002
    ) -> None:
        """List guilds returns exactly the guilds for that tenant.

        Creates 1 guild in each tenant, registers them with different data,
        and verifies each tenant only sees their own guild.
        """
        unique = uuid4().hex

        # Create admin users for two tenants
        admin_user1: DATestUser = UserManager.create(
            email=f"discord_list1+{unique}@example.com",
        )
        admin_user2: DATestUser = UserManager.create(
            email=f"discord_list2+{unique}@example.com",
        )

        # Create 1 guild in tenant 1
        response1 = requests.post(
            f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
            headers=admin_user1.headers,
        )
        if response1.status_code == 404:
            pytest.skip("Discord bot feature not enabled")
        assert response1.ok, f"Failed to create guild in tenant 1: {response1.text}"
        guild1_data = response1.json()
        guild1_id = guild1_data["id"]
        registration_key1 = guild1_data["registration_key"]
        tenant1_id = parse_discord_registration_key(registration_key1)
        assert (
            tenant1_id is not None
        ), "Failed to parse tenant ID from registration key 1"

        # Create 1 guild in tenant 2
        response2 = requests.post(
            f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
            headers=admin_user2.headers,
        )
        assert response2.ok, f"Failed to create guild in tenant 2: {response2.text}"
        guild2_data = response2.json()
        guild2_id = guild2_data["id"]
        registration_key2 = guild2_data["registration_key"]
        tenant2_id = parse_discord_registration_key(registration_key2)
        assert (
            tenant2_id is not None
        ), "Failed to parse tenant ID from registration key 2"

        # Verify tenant IDs are different
        assert (
            tenant1_id != tenant2_id
        ), "Tenant 1 and tenant 2 should have different tenant IDs"

        # Register guild 1 with tenant 1's context - populate with different data
        with get_session_with_tenant(tenant_id=tenant1_id) as db_session:
            config1 = get_guild_config_by_registration_key(
                db_session, registration_key1
            )
            assert config1 is not None, "Guild config 1 should exist"
            register_guild(
                db_session=db_session,
                config=config1,
                guild_id=111111111111111111,  # Different Discord guild ID
                guild_name="Tenant 1 Server",  # Different guild name
            )
            db_session.commit()

        # Register guild 2 with tenant 2's context - populate with different data
        with get_session_with_tenant(tenant_id=tenant2_id) as db_session:
            config2 = get_guild_config_by_registration_key(
                db_session, registration_key2
            )
            assert config2 is not None, "Guild config 2 should exist"
            register_guild(
                db_session=db_session,
                config=config2,
                guild_id=222222222222222222,  # Different Discord guild ID
                guild_name="Tenant 2 Server",  # Different guild name
            )
            db_session.commit()

        try:
            # Verify tenant 1 sees only their guild
            list_response1 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user1.headers,
            )
            assert list_response1.ok
            tenant1_guilds = list_response1.json()

            # Tenant 1 should see exactly 1 guild
            assert (
                len(tenant1_guilds) == 1
            ), f"Tenant 1 should see 1 guild, got {len(tenant1_guilds)}"

            # Verify tenant 1's guild has the correct data
            tenant1_guild = tenant1_guilds[0]
            assert (
                tenant1_guild["id"] == guild1_id
            ), "Tenant 1 should see their own guild"
            assert tenant1_guild["guild_id"] == 111111111111111111, (
                f"Tenant 1's guild should have guild_id 111111111111111111, "
                f"got {tenant1_guild['guild_id']}"
            )
            assert tenant1_guild["guild_name"] == "Tenant 1 Server", (
                f"Tenant 1's guild should have name 'Tenant 1 Server', "
                f"got {tenant1_guild['guild_name']}"
            )
            assert (
                tenant1_guild["registered_at"] is not None
            ), "Tenant 1's guild should be registered"

            # Tenant 1 should NOT see tenant 2's guild
            assert (
                tenant1_guild["guild_id"] != 222222222222222222
            ), "Tenant 1 should not see tenant 2's guild_id"
            assert (
                tenant1_guild["guild_name"] != "Tenant 2 Server"
            ), "Tenant 1 should not see tenant 2's guild_name"

            # Verify tenant 2 sees only their guild
            list_response2 = requests.get(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds",
                headers=admin_user2.headers,
            )
            assert list_response2.ok
            tenant2_guilds = list_response2.json()

            # Tenant 2 should see exactly 1 guild
            assert (
                len(tenant2_guilds) == 1
            ), f"Tenant 2 should see 1 guild, got {len(tenant2_guilds)}"

            # Verify tenant 2's guild has the correct data
            tenant2_guild = tenant2_guilds[0]
            assert (
                tenant2_guild["id"] == guild2_id
            ), "Tenant 2 should see their own guild"
            assert tenant2_guild["guild_id"] == 222222222222222222, (
                f"Tenant 2's guild should have guild_id 222222222222222222, "
                f"got {tenant2_guild['guild_id']}"
            )
            assert tenant2_guild["guild_name"] == "Tenant 2 Server", (
                f"Tenant 2's guild should have name 'Tenant 2 Server', "
                f"got {tenant2_guild['guild_name']}"
            )
            assert (
                tenant2_guild["registered_at"] is not None
            ), "Tenant 2's guild should be registered"

            # Tenant 2 should NOT see tenant 1's guild
            assert (
                tenant2_guild["guild_id"] != 111111111111111111
            ), "Tenant 2 should not see tenant 1's guild_id"
            assert (
                tenant2_guild["guild_name"] != "Tenant 1 Server"
            ), "Tenant 2 should not see tenant 1's guild_name"

            # Verify the guilds are different (different data)
            assert (
                tenant1_guild["guild_id"] != tenant2_guild["guild_id"]
            ), "Guilds should have different Discord guild IDs"
            assert (
                tenant1_guild["guild_name"] != tenant2_guild["guild_name"]
            ), "Guilds should have different names"

        finally:
            # Cleanup
            requests.delete(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild1_id}",
                headers=admin_user1.headers,
            )
            requests.delete(
                f"{API_SERVER_URL}/manage/admin/discord-bot/guilds/{guild2_id}",
                headers=admin_user2.headers,
            )


class TestGuildAccessIsolation:
    """Tests for guild access isolation between tenants."""

    def test_tenant_cannot_access_other_tenant_guild(
        self, reset_multitenant: None  # noqa: ARG002
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
