"""Integration tests for Discord bot API endpoints.

These tests hit actual API endpoints via HTTP requests.
"""

import pytest
import requests

from onyx.db.discord_bot import get_discord_service_api_key
from onyx.db.discord_bot import get_or_create_discord_service_api_key
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.managers.discord_bot import DiscordBotManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


class TestBotConfigEndpoints:
    """Tests for /manage/admin/discord-bot/config endpoints."""

    def test_get_bot_config_not_configured(self, reset: None) -> None:  # noqa: ARG002
        """GET /config returns configured=False when no config exists."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Ensure no config exists
        DiscordBotManager.delete_bot_config_if_exists(admin_user)

        config = DiscordBotManager.get_bot_config(admin_user)

        assert config["configured"] is False
        assert "created_at" not in config or config.get("created_at") is None

    def test_create_bot_config(self, reset: None) -> None:  # noqa: ARG002
        """POST /config creates a new bot config."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Ensure no config exists
        DiscordBotManager.delete_bot_config_if_exists(admin_user)

        config = DiscordBotManager.create_bot_config(
            bot_token="test_token_123",
            user_performing_action=admin_user,
        )

        assert config["configured"] is True
        assert "created_at" in config

        # Cleanup
        DiscordBotManager.delete_bot_config_if_exists(admin_user)

    def test_create_bot_config_already_exists(
        self, reset: None  # noqa: ARG002
    ) -> None:
        """POST /config returns 409 if config already exists."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Ensure no config exists, then create one
        DiscordBotManager.delete_bot_config_if_exists(admin_user)
        DiscordBotManager.create_bot_config(
            bot_token="token1",
            user_performing_action=admin_user,
        )

        # Try to create another - should fail
        with pytest.raises(requests.HTTPError) as exc_info:
            DiscordBotManager.create_bot_config(
                bot_token="token2",
                user_performing_action=admin_user,
            )

        assert exc_info.value.response.status_code == 409

        # Cleanup
        DiscordBotManager.delete_bot_config_if_exists(admin_user)

    def test_delete_bot_config(self, reset: None) -> None:  # noqa: ARG002
        """DELETE /config removes the bot config."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Ensure no config exists, then create one
        DiscordBotManager.delete_bot_config_if_exists(admin_user)
        DiscordBotManager.create_bot_config(
            bot_token="test_token",
            user_performing_action=admin_user,
        )

        # Delete it
        result = DiscordBotManager.delete_bot_config(admin_user)
        assert result["deleted"] is True

        # Verify it's gone
        config = DiscordBotManager.get_bot_config(admin_user)
        assert config["configured"] is False

    def test_delete_bot_config_not_found(self, reset: None) -> None:  # noqa: ARG002
        """DELETE /config returns 404 if no config exists."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Ensure no config exists
        DiscordBotManager.delete_bot_config_if_exists(admin_user)

        # Try to delete - should fail
        with pytest.raises(requests.HTTPError) as exc_info:
            DiscordBotManager.delete_bot_config(admin_user)

        assert exc_info.value.response.status_code == 404


class TestGuildConfigEndpoints:
    """Tests for /manage/admin/discord-bot/guilds endpoints."""

    def test_create_guild_config(self, reset: None) -> None:  # noqa: ARG002
        """POST /guilds creates a new guild config with registration key."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guild = DiscordBotManager.create_guild(admin_user)

        assert guild.id is not None
        assert guild.registration_key is not None
        assert guild.registration_key.startswith("discord_")

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_list_guilds(self, reset: None) -> None:  # noqa: ARG002
        """GET /guilds returns all guild configs."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create some guilds
        guild1 = DiscordBotManager.create_guild(admin_user)
        guild2 = DiscordBotManager.create_guild(admin_user)

        guilds = DiscordBotManager.list_guilds(admin_user)

        guild_ids = [g["id"] for g in guilds]
        assert guild1.id in guild_ids
        assert guild2.id in guild_ids

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild1.id, admin_user)
        DiscordBotManager.delete_guild_if_exists(guild2.id, admin_user)

    def test_get_guild_config(self, reset: None) -> None:  # noqa: ARG002
        """GET /guilds/{config_id} returns the specific guild config."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guild = DiscordBotManager.create_guild(admin_user)

        fetched = DiscordBotManager.get_guild(guild.id, admin_user)

        assert fetched["id"] == guild.id
        assert fetched["enabled"] is True  # Default
        assert fetched["guild_id"] is None  # Not registered yet
        assert fetched["guild_name"] is None

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_get_guild_config_not_found(self, reset: None) -> None:  # noqa: ARG002
        """GET /guilds/{config_id} returns 404 for non-existent guild."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        result = DiscordBotManager.get_guild_or_none(999999, admin_user)
        assert result is None

    def test_update_guild_config(self, reset: None) -> None:  # noqa: ARG002
        """PATCH /guilds/{config_id} updates the guild config."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guild = DiscordBotManager.create_guild(admin_user)

        # Update enabled status
        updated = DiscordBotManager.update_guild(
            guild.id,
            admin_user,
            enabled=False,
        )

        assert updated["enabled"] is False

        # Verify persistence
        fetched = DiscordBotManager.get_guild(guild.id, admin_user)
        assert fetched["enabled"] is False

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_delete_guild_config(self, reset: None) -> None:  # noqa: ARG002
        """DELETE /guilds/{config_id} removes the guild config."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guild = DiscordBotManager.create_guild(admin_user)

        # Delete it
        result = DiscordBotManager.delete_guild(guild.id, admin_user)
        assert result["deleted"] is True

        # Verify it's gone
        assert DiscordBotManager.get_guild_or_none(guild.id, admin_user) is None

    def test_delete_guild_config_not_found(self, reset: None) -> None:  # noqa: ARG002
        """DELETE /guilds/{config_id} returns 404 for non-existent guild."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        with pytest.raises(requests.HTTPError) as exc_info:
            DiscordBotManager.delete_guild(999999, admin_user)

        assert exc_info.value.response.status_code == 404

    def test_registration_key_format(self, reset: None) -> None:  # noqa: ARG002
        """Registration key has proper format with tenant encoded."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guild = DiscordBotManager.create_guild(admin_user)

        # Key should be: discord_{encoded_tenant}.{random}
        key = guild.registration_key
        assert key is not None
        assert key.startswith("discord_")

        # Should have two parts separated by dot
        key_body = key.removeprefix("discord_")
        parts = key_body.split(".", 1)
        assert len(parts) == 2

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_each_registration_key_is_unique(self, reset: None) -> None:  # noqa: ARG002
        """Each created guild gets a unique registration key."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        guilds = [DiscordBotManager.create_guild(admin_user) for _ in range(5)]
        keys = [g.registration_key for g in guilds]

        assert len(set(keys)) == 5  # All unique

        # Cleanup
        for guild in guilds:
            DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)


class TestChannelConfigEndpoints:
    """Tests for /manage/admin/discord-bot/guilds/{id}/channels endpoints."""

    def test_list_channels_empty(self, reset: None) -> None:  # noqa: ARG002
        """GET /guilds/{id}/channels returns empty list when no channels exist."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=111111111,
            guild_name="Test Guild",
        )

        channels = DiscordBotManager.list_channels(guild.id, admin_user)

        assert channels == []

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_list_channels_with_data(self, reset: None) -> None:  # noqa: ARG002
        """GET /guilds/{id}/channels returns channel configs."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=222222222,
            guild_name="Test Guild",
        )

        # Create test channels directly in DB
        channel1 = DiscordBotManager.create_test_channel_in_db(
            guild_config_id=guild.id,
            channel_id=123456789,
            channel_name="general",
        )
        channel2 = DiscordBotManager.create_test_channel_in_db(
            guild_config_id=guild.id,
            channel_id=987654321,
            channel_name="help",
            channel_type="forum",
        )

        channels = DiscordBotManager.list_channels(guild.id, admin_user)

        assert len(channels) == 2
        channel_ids = [c.id for c in channels]
        assert channel1.id in channel_ids
        assert channel2.id in channel_ids

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_update_channel_enabled(self, reset: None) -> None:  # noqa: ARG002
        """PATCH /guilds/{id}/channels/{id} updates enabled status."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=333333333,
            guild_name="Test Guild",
        )
        channel = DiscordBotManager.create_test_channel_in_db(
            guild_config_id=guild.id,
            channel_id=123456789,
            channel_name="general",
        )

        # Default is disabled
        assert channel.enabled is False

        # Enable the channel
        updated = DiscordBotManager.update_channel(
            guild.id,
            channel.id,
            admin_user,
            enabled=True,
        )

        assert updated.enabled is True

        # Verify persistence
        channels = DiscordBotManager.list_channels(guild.id, admin_user)
        found = next(c for c in channels if c.id == channel.id)
        assert found.enabled is True

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_update_channel_thread_only_mode(self, reset: None) -> None:  # noqa: ARG002
        """PATCH /guilds/{id}/channels/{id} updates thread_only_mode."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=444444444,
            guild_name="Test Guild",
        )
        channel = DiscordBotManager.create_test_channel_in_db(
            guild_config_id=guild.id,
            channel_id=123456789,
            channel_name="general",
        )

        # Default is False
        assert channel.thread_only_mode is False

        # Enable thread_only_mode
        updated = DiscordBotManager.update_channel(
            guild.id,
            channel.id,
            admin_user,
            thread_only_mode=True,
        )

        assert updated.thread_only_mode is True

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_update_channel_require_bot_invocation(
        self, reset: None  # noqa: ARG002
    ) -> None:
        """PATCH /guilds/{id}/channels/{id} updates require_bot_invocation."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=555555555,
            guild_name="Test Guild",
        )
        channel = DiscordBotManager.create_test_channel_in_db(
            guild_config_id=guild.id,
            channel_id=123456789,
            channel_name="general",
        )

        # Default is True
        assert channel.require_bot_invocation is True

        # Disable require_bot_invocation
        updated = DiscordBotManager.update_channel(
            guild.id,
            channel.id,
            admin_user,
            require_bot_invocation=False,
        )

        assert updated.require_bot_invocation is False

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)

    def test_update_channel_not_found(self, reset: None) -> None:  # noqa: ARG002
        """PATCH /guilds/{id}/channels/{id} returns 404 for non-existent channel."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Create a registered guild (has guild_id set)
        guild = DiscordBotManager.create_registered_guild_in_db(
            guild_id=666666666,
            guild_name="Test Guild",
        )

        with pytest.raises(requests.HTTPError) as exc_info:
            DiscordBotManager.update_channel(
                guild.id,
                999999,
                admin_user,
                enabled=True,
            )

        assert exc_info.value.response.status_code == 404

        # Cleanup
        DiscordBotManager.delete_guild_if_exists(guild.id, admin_user)


class TestServiceApiKeyCleanup:
    """Tests for service API key cleanup when bot/guild configs are deleted."""

    def test_delete_bot_config_also_deletes_service_api_key(
        self, reset: None  # noqa: ARG002
    ) -> None:
        """DELETE /config also deletes the service API key (self-hosted flow)."""
        admin_user: DATestUser = UserManager.create(name="admin_user")

        # Setup: create bot config via API
        DiscordBotManager.delete_bot_config_if_exists(admin_user)
        DiscordBotManager.create_bot_config(
            bot_token="test_token",
            user_performing_action=admin_user,
        )

        # Create service API key directly in DB (simulating bot registration)
        with get_session_with_current_tenant() as db_session:
            get_or_create_discord_service_api_key(db_session, "public")
            db_session.commit()

            # Verify it exists
            assert get_discord_service_api_key(db_session) is not None

        # Delete bot config via API
        result = DiscordBotManager.delete_bot_config(admin_user)
        assert result["deleted"] is True

        # Verify service API key was also deleted
        with get_session_with_current_tenant() as db_session:
            assert get_discord_service_api_key(db_session) is None
