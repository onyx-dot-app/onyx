"""Discord bot command handlers for registration and channel sync."""

import asyncio
from datetime import datetime
from datetime import timezone

import discord

from onyx.configs.app_configs import DISCORD_BOT_INVOKE_CHAR
from onyx.configs.constants import ONYX_DISCORD_URL
from onyx.db.discord_bot import bulk_create_channel_configs
from onyx.db.discord_bot import get_guild_config_by_discord_id
from onyx.db.discord_bot import get_guild_config_by_internal_id
from onyx.db.discord_bot import get_guild_config_by_registration_key
from onyx.db.discord_bot import sync_channel_configs
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.utils import DiscordChannelView
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.onyxbot.discord.constants import REGISTER_COMMAND
from onyx.onyxbot.discord.constants import SYNC_CHANNELS_COMMAND
from onyx.onyxbot.discord.exceptions import GuildAlreadyRegisteredError
from onyx.onyxbot.discord.exceptions import InvalidRegistrationKeyError
from onyx.onyxbot.discord.exceptions import RegistrationError
from onyx.onyxbot.discord.exceptions import RegistrationKeyAlreadyUsedError
from onyx.onyxbot.discord.exceptions import RegistrationKeyNotFoundError
from onyx.onyxbot.discord.exceptions import RegistrationPermissionError
from onyx.onyxbot.discord.exceptions import SyncChannelsError
from onyx.onyxbot.discord.exceptions import SyncChannelsPermissionError
from onyx.onyxbot.discord.exceptions import SyncChannelsServerNotFoundError
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


async def handle_dm(message: discord.Message) -> None:
    """Handle direct messages."""
    dm_response = (
        "**I can't respond to DMs** :sweat:\n\n"
        f"Please chat with me in a server channel, or join the official "
        f"[Onyx Discord]({ONYX_DISCORD_URL}) for help!"
    )
    await message.channel.send(dm_response)


# -------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------


async def handle_registration_command(
    message: discord.Message,
    cache: DiscordCacheManager,
) -> bool:
    """Handle !register command. Returns True if command was handled."""
    if not message.guild:
        raise RegistrationError("This command can only be used in a server.")

    content = message.content.strip()

    # Check for !register command
    if not content.startswith(f"{DISCORD_BOT_INVOKE_CHAR}{REGISTER_COMMAND}"):
        return False

    guild_name = message.guild.name
    logger.info(f"Registration command received: {guild_name}")

    # Parse the registration key
    parts = content.split(maxsplit=1)
    if len(parts) < 2:
        raise InvalidRegistrationKeyError(
            "Invalid registration key format. Please check the key and try again."
        )

    registration_key = parts[1].strip()

    if not message.author or not isinstance(message.author, discord.Member):
        raise RegistrationPermissionError(
            "You need to be a server administrator to register the bot."
        )

    # Check permissions - require admin or manage_guild
    if not message.author.guild_permissions.administrator:
        if not message.author.guild_permissions.manage_guild:
            raise RegistrationPermissionError(
                "You need **Administrator** or **Manage Server** permissions to register this bot."
            )

    # Process registration
    try:
        await _register_guild(message, registration_key, cache)
        logger.info(f"Registration successful: {guild_name}")
        await message.reply(
            ":white_check_mark: **Successfully registered!**\n\n"
            "This server is now connected to Onyx. "
            "I'll respond to messages based on your server and channel settings set in Onyx."
        )
    except InvalidRegistrationKeyError:
        logger.debug(f"Registration failed - invalid key: {guild_name}")
        await message.reply(
            ":x: **Invalid registration key format.**\n\n"
            "Please check the key and try again."
        )
    except RegistrationKeyNotFoundError:
        logger.debug(f"Registration failed - key not found: {guild_name}")
        await message.reply(
            ":x: **Registration key not found.**\n\n"
            "The key may have expired or been deleted. "
            "Please generate a new one from the Onyx admin panel."
        )
    except RegistrationKeyAlreadyUsedError:
        logger.debug(f"Registration failed - key already used: {guild_name}")
        await message.reply(
            ":x: **This registration key has already been used.**\n\n"
            "Each key can only be used once. "
            "Please generate a new key from the Onyx admin panel."
        )
    except GuildAlreadyRegisteredError:
        logger.debug(f"Registration failed - guild already registered: {guild_name}")
        await message.reply(
            ":x: **This server is already registered.**\n\n"
            "OnyxBot can only connect one Discord server to one Onyx workspace."
        )
    except RegistrationError as e:
        logger.warning(f"Registration failed: {guild_name}, error={e}")
        await message.reply(
            f":x: **Registration failed: {e}**\n\n" "Please try again later."
        )
    except Exception:
        logger.exception(f"Registration failed unexpectedly: {guild_name}")
        await message.reply(
            ":x: **Registration failed.**\n\n"
            "An unexpected error occurred. Please try again later."
        )

    return True


async def _register_guild(
    message: discord.Message,
    registration_key: str,
    cache: DiscordCacheManager,
) -> None:
    """Register a guild with a registration key."""
    if not message.guild:
        # mypy, even though we already know that message.guild is not None
        raise RegistrationError("This command can only be used in a server.")

    logger.info(f"Guild '{message.guild.name}' attempting to register Discord bot")
    registration_key = registration_key.strip()

    # Parse tenant_id from registration key
    parsed = parse_discord_registration_key(registration_key)
    if parsed is None:
        raise InvalidRegistrationKeyError()

    tenant_id = parsed

    logger.info(f"Parsed tenant_id {tenant_id} from registration key")

    # Check if this guild is already registered to any tenant
    guild_id = message.guild.id
    existing_tenant = cache.get_tenant(guild_id)
    if existing_tenant is not None:
        logger.warning(
            f"Guild {guild_id} is already registered to tenant {existing_tenant}"
        )
        raise GuildAlreadyRegisteredError(
            "This server is already registered to another Onyx workspace."
        )

    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        guild = message.guild
        guild_name = guild.name

        # Collect all text channels from the guild
        channels = get_text_channels(guild)
        logger.info(f"Found {len(channels)} text channels in guild '{guild_name}'")

        # Validate and update in database
        def _sync_register() -> int:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                # Find the guild config by registration key
                config = get_guild_config_by_registration_key(db, registration_key)
                if not config:
                    raise RegistrationKeyNotFoundError(
                        f"Key not found for tenant {tenant_id}"
                    )

                # Check if already used
                if config.guild_id is not None:
                    raise RegistrationKeyAlreadyUsedError(
                        f"Key already registered by guild {config.guild_id}"
                    )

                # Update the guild config
                config.guild_id = guild_id
                config.guild_name = guild_name
                config.registered_at = datetime.now(timezone.utc)

                # Create channel configs for all text channels
                bulk_create_channel_configs(db, config.id, channels)

                db.commit()
                return config.id

        await asyncio.to_thread(_sync_register)

        # Refresh cache for this guild
        await cache.refresh_guild(guild_id, tenant_id)

        logger.info(
            f"Guild '{guild_name}' registered with {len(channels)} channel configs"
        )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)


def get_text_channels(guild: discord.Guild) -> list[DiscordChannelView]:
    """Get all text channels from a guild as DiscordChannelView objects."""
    channels: list[DiscordChannelView] = []
    for channel in guild.channels:
        # Include text channels and forum channels (where threads can be created)
        if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            # Check if channel is private (not visible to @everyone)
            everyone_perms = channel.permissions_for(guild.default_role)
            is_private = not everyone_perms.view_channel

            logger.debug(
                f"Found channel: #{channel.name}, "
                f"type={channel.type.name}, is_private={is_private}"
            )

            channels.append(
                DiscordChannelView(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    channel_type=channel.type.name,  # "text" or "forum"
                    is_private=is_private,
                )
            )

    logger.debug(f"Retrieved {len(channels)} channels from guild '{guild.name}'")
    return channels


# -------------------------------------------------------------------------
# Sync Channels
# -------------------------------------------------------------------------


async def handle_sync_channels_command(
    message: discord.Message,
    tenant_id: str | None,
    bot: discord.Client,
) -> bool:
    """Handle !sync-channels command. Returns True if command was handled."""
    try:
        if not message.guild:
            raise SyncChannelsError("This command can only be used in a server.")

        content = message.content.strip()

        # Check for !sync-channels command
        if not content.startswith(f"{DISCORD_BOT_INVOKE_CHAR}{SYNC_CHANNELS_COMMAND}"):
            return False

        guild_name = message.guild.name
        logger.info(f"Sync-channels command received: {guild_name}")

        # Must be registered
        if not tenant_id:
            raise SyncChannelsServerNotFoundError(
                "This server is not registered. Please register it first."
            )

        # Check permissions - require admin or manage_guild
        if not message.author or not isinstance(message.author, discord.Member):
            raise SyncChannelsPermissionError(
                "You need to be a server administrator to sync channels."
            )

        if not message.author.guild_permissions.administrator:
            if not message.author.guild_permissions.manage_guild:
                raise SyncChannelsPermissionError(
                    "You need **Administrator** or **Manage Server** permissions to sync channels."
                )

        # Get guild config ID
        def _get_guild_config_id() -> int | None:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                if not message.guild:
                    raise SyncChannelsServerNotFoundError(
                        "Guild not found. This shouldn't happen. Please contact support."
                    )
                config = get_guild_config_by_discord_id(db, message.guild.id)
                return config.id if config else None

        guild_config_id = await asyncio.to_thread(_get_guild_config_id)

        if not guild_config_id:
            raise SyncChannelsServerNotFoundError(
                "Guild config not found. This shouldn't happen. Please contact support."
            )

        # Perform the sync
        added, removed, updated = await sync_guild_channels(
            guild_config_id, tenant_id, bot
        )
        logger.info(
            f"Sync-channels successful: {guild_name}, "
            f"added={added}, removed={removed}, updated={updated}"
        )
        await message.reply(
            f":white_check_mark: **Channel sync complete!**\n\n"
            f"* **{added}** new channel(s) added\n"
            f"* **{removed}** deleted channel(s) removed\n"
            f"* **{updated}** channel name(s) updated\n\n"
            "New channels are disabled by default. Enable them in the Onyx admin panel."
        )
    except SyncChannelsPermissionError:
        await message.reply(
            ":x: **You need **Administrator** or **Manage Server** permissions to sync channels.**"
        )
    except SyncChannelsServerNotFoundError:
        await message.reply(
            ":x: **Guild config not found.**\n\n"
            "This server is not registered. Please register it first."
        )
    except SyncChannelsError:
        logger.warning(
            f"Sync-channels failed: {message.guild.name if message.guild else 'unknown'}"
        )
        await message.reply(
            ":x: **Channel sync failed.**\n\nPlease try again later :sweat_smile:"
        )
    except Exception:
        logger.exception(
            f"Sync-channels failed unexpectedly: {message.guild.name if message.guild else 'unknown'}"
        )
        await message.reply(
            ":x: **Channel sync failed.**\n\nYou may want to contact Onyx for support :sweat_smile:"
        )

    return True


async def sync_guild_channels(
    guild_config_id: int,
    tenant_id: str,
    bot: discord.Client,
) -> tuple[int, int, int]:
    """Sync channel configs with current Discord channels for a guild.

    Fetches current channels from Discord and syncs with database:
    - Creates configs for new channels (disabled by default)
    - Removes configs for deleted channels
    - Updates names for existing channels if changed

    Args:
        guild_config_id: Internal ID of the guild config
        tenant_id: Tenant ID for database access
        bot: Discord bot client

    Returns:
        (added_count, removed_count, updated_count)

    Raises:
        ValueError: If guild config not found or guild not registered
    """
    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        # Get guild_id from config
        def _get_guild_id() -> int | None:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                config = get_guild_config_by_internal_id(db, guild_config_id)
                if not config:
                    return None
                return config.guild_id

        guild_id = await asyncio.to_thread(_get_guild_id)

        if guild_id is None:
            raise ValueError(
                f"Guild config {guild_config_id} not found or not registered"
            )

        # Get the guild from Discord
        guild = bot.get_guild(guild_id)
        if not guild:
            raise ValueError(f"Guild {guild_id} not found in Discord cache")

        # Get current channels from Discord
        channels = get_text_channels(guild)
        logger.info(f"Syncing {len(channels)} channels for guild '{guild.name}'")

        # Sync with database
        def _sync() -> tuple[int, int, int]:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                added, removed, updated = sync_channel_configs(
                    db, guild_config_id, channels
                )
                db.commit()
                return added, removed, updated

        added, removed, updated = await asyncio.to_thread(_sync)

        logger.info(
            f"Channel sync complete for guild '{guild.name}': "
            f"added={added}, removed={removed}, updated={updated}"
        )

        return added, removed, updated

    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
