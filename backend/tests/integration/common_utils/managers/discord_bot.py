"""Manager for Discord bot API integration tests."""

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
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
    ) -> list[dict]:
        """List all channel configs for a guild."""
        response = requests.get(
            url=f"{DISCORD_BOT_API_URL}/guilds/{guild_config_id}/channels",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def update_channel(
        guild_config_id: int,
        channel_config_id: int,
        user_performing_action: DATestUser,
        enabled: bool | None = None,
        thread_only_mode: bool | None = None,
        require_bot_invocation: bool | None = None,
        persona_override_id: int | None = None,
    ) -> dict:
        """Update a channel config."""
        body: dict = {}
        if enabled is not None:
            body["enabled"] = enabled
        if thread_only_mode is not None:
            body["thread_only_mode"] = thread_only_mode
        if require_bot_invocation is not None:
            body["require_bot_invocation"] = require_bot_invocation
        if persona_override_id is not None:
            body["persona_override_id"] = persona_override_id

        response = requests.patch(
            url=f"{DISCORD_BOT_API_URL}/guilds/{guild_config_id}/channels/{channel_config_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            json=body,
        )
        response.raise_for_status()
        return response.json()

    # === Utility methods for testing ===

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
