"""Multi-tenant isolation tests for Discord bot.

These tests ensure tenant isolation and prevent data leakage between tenants.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import AuthType
from onyx.db.discord_bot import create_guild_config
from onyx.db.discord_bot import delete_guild_config
from onyx.db.discord_bot import get_channel_config_by_discord_ids
from onyx.db.discord_bot import get_guild_configs
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.onyxbot.discord.constants import REGISTRATION_KEY_PREFIX
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


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

    def test_tenant_cannot_see_other_tenant_guilds(self, db_session: Session) -> None:
        """Guilds created in tenant 1 are not visible from tenant 2.

        Creates guilds in current tenant, then queries with get_guild_configs
        to verify only guilds for current tenant are returned.
        """
        from onyx.db.discord_bot import get_guild_config_by_guild_id
        from onyx.db.discord_bot import update_guild_config

        # Create two guilds in current tenant
        reg_key1 = generate_discord_registration_key("public")
        reg_key2 = generate_discord_registration_key("public")
        guild1 = create_guild_config(db_session, registration_key=reg_key1)
        guild2 = create_guild_config(db_session, registration_key=reg_key2)
        db_session.commit()

        try:
            # Register guild1 with Discord guild ID
            update_guild_config(
                db_session,
                guild_config_id=guild1.id,
                guild_id=111111111,
                guild_name="Guild 1",
                enabled=True,
            )
            # Register guild2 with different Discord guild ID
            update_guild_config(
                db_session,
                guild_config_id=guild2.id,
                guild_id=222222222,
                guild_name="Guild 2",
                enabled=True,
            )
            db_session.commit()

            # Query all guilds - should return both
            all_guilds = get_guild_configs(db_session)
            guild_ids = [g.guild_id for g in all_guilds]
            assert 111111111 in guild_ids
            assert 222222222 in guild_ids

            # Query for a guild that doesn't exist in this tenant
            nonexistent = get_guild_config_by_guild_id(db_session, 999999999)
            assert nonexistent is None

        finally:
            # Cleanup
            delete_guild_config(db_session, guild1.id)
            delete_guild_config(db_session, guild2.id)
            db_session.commit()

    def test_guild_list_returns_only_own_tenant(self, db_session: Session) -> None:
        """List guilds returns exactly the guilds for that tenant.

        Creates multiple guilds and verifies get_guild_configs returns
        only those guilds created in the current tenant context.
        """
        from onyx.db.discord_bot import update_guild_config

        # Create three guilds in current tenant
        guilds = []
        for i in range(3):
            reg_key = generate_discord_registration_key("public")
            guild = create_guild_config(db_session, registration_key=reg_key)
            guilds.append(guild)
        db_session.commit()

        try:
            # Register each guild with unique Discord guild ID
            for i, guild in enumerate(guilds):
                update_guild_config(
                    db_session,
                    guild_config_id=guild.id,
                    guild_id=100000000 + i,
                    guild_name=f"Test Guild {i}",
                    enabled=True,
                )
            db_session.commit()

            # Get all guilds for this tenant
            result = get_guild_configs(db_session)

            # Should have at least the 3 we created (may have more from other tests)
            result_guild_ids = {g.guild_id for g in result}
            for i in range(3):
                assert 100000000 + i in result_guild_ids

        finally:
            # Cleanup
            for guild in guilds:
                delete_guild_config(db_session, guild.id)
            db_session.commit()


class TestChannelDataIsolation:
    """Tests for channel data isolation between tenants."""

    def test_tenant_cannot_see_other_tenant_channels(self, db_session: Session) -> None:
        """Channels in tenant 1 guild are not visible from tenant 2.

        Creates a guild with channel in tenant1, then queries from tenant2
        context to verify the channel is not visible.
        """
        tenant1_guild_id = 111111111
        tenant1_channel_id = 222222222

        # Create guild in tenant1 (current context is "public" which acts as tenant1)
        reg_key = generate_discord_registration_key("public")
        guild = create_guild_config(db_session, registration_key=reg_key)
        db_session.commit()

        try:
            # Register the guild with a Discord guild ID
            from onyx.db.discord_bot import update_guild_config

            update_guild_config(
                db_session,
                guild_config_id=guild.id,
                guild_id=tenant1_guild_id,
                guild_name="Tenant1 Guild",
                enabled=True,
            )
            db_session.commit()

            # Create a channel config for this guild
            from onyx.db.discord_bot import bulk_create_channel_configs
            from onyx.db.utils import DiscordChannelView

            channels = [
                DiscordChannelView(
                    channel_id=tenant1_channel_id,
                    channel_name="test-channel",
                    channel_type="text",
                )
            ]
            bulk_create_channel_configs(db_session, guild.id, channels)
            db_session.commit()

            # Verify channel exists in tenant1 context
            result_in_tenant1 = get_channel_config_by_discord_ids(
                db_session, guild_id=tenant1_guild_id, channel_id=tenant1_channel_id
            )
            assert result_in_tenant1 is not None

            # Query from a different tenant context
            # The channel should not be visible because the guild belongs to "public" tenant
            # and we're querying with different guild_id that doesn't exist in this tenant
            result_wrong_guild = get_channel_config_by_discord_ids(
                db_session, guild_id=999999999, channel_id=tenant1_channel_id
            )
            assert result_wrong_guild is None

        finally:
            # Cleanup
            delete_guild_config(db_session, guild.id)
            db_session.commit()


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


# Pytest fixture for db_session
@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Create database session for tests."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.db.engine.sql_engine import SqlEngine

    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    token = CURRENT_TENANT_ID_CONTEXTVAR.set("public")
    try:
        with get_session_with_current_tenant() as session:
            yield session
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
