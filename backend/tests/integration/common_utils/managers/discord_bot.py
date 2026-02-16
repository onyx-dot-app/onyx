"""Manager for Discord bot API integration tests."""

import requests

from onyx.db.discord_bot import create_channel_config
from onyx.db.discord_bot import create_guild_config
from onyx.db.discord_bot import register_guild
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.utils import DiscordChannelView
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestDiscordChannelConfig
from tests.integration.common_utils.test_models import DATestDiscordGuildConfig
from tests.integration.common_utils.test_models import DATestUser

DISCORD_BOT_API_URL = f"{API_SERVER_URL}/manage/admin/discord-bot"


class DiscordBotManager:
    """Manager for Discord bot API operations."""

    # === Bot Config ===

    @staticmethod
    def get_bot_config(
        user_performing_action: DATestUser,
    ) -> dict:
        """Get Discord bot config."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/config",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def create_bot_config(
        bot_token: str,
        user_performing_action: DATestUser,
    ) -> dict:
        """Create Discord bot config."""
        response = requests.post(
            url=f"{DISCORD_BOT_API_URL}/config",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            json={"bot_token": bot_token},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete_bot_config(
        user_performing_action: DATestUser,
    ) -> dict:
        """Delete Discord bot config."""
        response = requests.delete(
            url=f"{DISCORD_BOT_API_URL}/config",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    # === Guild Config ===

    @staticmethod
    def list_guilds(
        user_performing_action: DATestUser,
    ) -> list[dict]:
        """List all guild configs."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/guilds",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def create_guild(
        user_performing_action: DATestUser,
    ) -> DATestDiscordGuildConfig:
        """Create a new guild config with registration key."""
        response = requests.post(
            url=f"{DISCORD_BOT_API_URL}/guilds",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        data = response.json()
        return DATestDiscordGuildConfig(
            id=data["id"],
            registration_key=data["registration_key"],
        )

    @staticmethod
    def get_guild(
        config_id: int,
        user_performing_action: DATestUser,
    ) -> dict:
        """Get a specific guild config."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/guilds/{config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def update_guild(
        config_id: int,
        user_performing_action: DATestUser,
        enabled: bool | None = None,
        default_persona_id: int | None = None,
    ) -> dict:
        """Update a guild config."""
        # Fetch current guild config to get existing values
        current_guild = DiscordBotManager.get_guild(config_id, user_performing_action)

        # Build request body with required fields
        body: dict = {
            "enabled": enabled if enabled is not None else current_guild["enabled"],
            "default_persona_id": (
                default_persona_id
                if default_persona_id is not None
                else current_guild.get("default_persona_id")
            ),
        }

        response = requests.patch(
            url=f"{DISCORD_BOT_API_URL}/guilds/{config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            json=body,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete_guild(
        config_id: int,
        user_performing_action: DATestUser,
    ) -> dict:
        """Delete a guild config."""
        response = requests.delete(
            url=f"{DISCORD_BOT_API_URL}/guilds/{config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    # === Channel Config ===

    @staticmethod
    def list_channels(
        guild_config_id: int,
        user_performing_action: DATestUser,
    ) -> list[DATestDiscordChannelConfig]:
        """List all channel configs for a guild."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/guilds/{guild_config_id}/channels",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return [DATestDiscordChannelConfig(**c) for c in response.json()]

    @staticmethod
    def update_channel(
        guild_config_id: int,
        channel_config_id: int,
        user_performing_action: DATestUser,
        enabled: bool = False,
        thread_only_mode: bool = False,
        require_bot_invocation: bool = True,
        persona_override_id: int | None = None,
    ) -> DATestDiscordChannelConfig:
        """Update a channel config.

        All fields are required by the API. Default values match the channel
        config defaults from create_channel_config.
        """
        body: dict = {
            "enabled": enabled,
            "thread_only_mode": thread_only_mode,
            "require_bot_invocation": require_bot_invocation,
            "persona_override_id": persona_override_id,
        }

        response = requests.patch(
            url=f"{DISCORD_BOT_API_URL}/guilds/{guild_config_id}/channels/{channel_config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            json=body,
        )
        response.raise_for_status()
        return DATestDiscordChannelConfig(**response.json())

    # === Utility methods for testing ===

    @staticmethod
    def create_registered_guild_in_db(
        guild_id: int,
        guild_name: str,
    ) -> DATestDiscordGuildConfig:
        """Create a registered guild config directly in the database.

        This creates a guild that has already completed registration,
        with guild_id and guild_name set. Use this for testing channel
        endpoints which require a registered guild.
        """
        with get_session_with_current_tenant() as db_session:
            tenant_id = get_current_tenant_id()
            registration_key = generate_discord_registration_key(tenant_id)
            config = create_guild_config(db_session, registration_key)
            config = register_guild(db_session, config, guild_id, guild_name)
            db_session.commit()

            return DATestDiscordGuildConfig(
                id=config.id,
                registration_key=registration_key,
            )

    @staticmethod
    def get_guild_or_none(
        config_id: int,
        user_performing_action: DATestUser,
    ) -> dict | None:
        """Get a guild config, returning None if not found."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/guilds/{config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete_guild_if_exists(
        config_id: int,
        user_performing_action: DATestUser,
    ) -> bool:
        """Delete a guild config if it exists. Returns True if deleted."""
        response = requests.delete(
            url=f"{DISCORD_BOT_API_URL}/guilds/{config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    @staticmethod
    def delete_bot_config_if_exists(
        user_performing_action: DATestUser,
    ) -> bool:
        """Delete bot config if it exists. Returns True if deleted."""
        response = requests.delete(
            url=f"{DISCORD_BOT_API_URL}/config",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    @staticmethod
    def create_test_channel_in_db(
        guild_config_id: int,
        channel_id: int,
        channel_name: str,
        channel_type: str = "text",
        is_private: bool = False,
    ) -> DATestDiscordChannelConfig:
        """Create a test channel config directly in the database.

        This is needed because channels are normally synced from Discord,
        not created via API. For testing the channel API endpoints,
        we need to populate test data directly.
        """
        with get_session_with_current_tenant() as db_session:
            channel_view = DiscordChannelView(
                channel_id=channel_id,
                channel_name=channel_name,
                channel_type=channel_type,
                is_private=is_private,
            )
            config = create_channel_config(db_session, guild_config_id, channel_view)
            db_session.commit()

            return DATestDiscordChannelConfig(
                id=config.id,
                guild_config_id=config.guild_config_id,
                channel_id=config.channel_id,
                channel_name=config.channel_name,
                channel_type=config.channel_type,
                is_private=config.is_private,
                enabled=config.enabled,
                thread_only_mode=config.thread_only_mode,
                require_bot_invocation=config.require_bot_invocation,
                persona_override_id=config.persona_override_id,
            )
