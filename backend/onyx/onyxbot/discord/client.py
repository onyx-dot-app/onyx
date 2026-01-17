"""Discord bot client with integrated message handling."""

import asyncio
import time

import discord
from discord.ext import commands

from onyx.configs.app_configs import DISCORD_BOT_INVOKE_CHAR
from onyx.onyxbot.discord.api_client import OnyxAPIClient
from onyx.onyxbot.discord.cache import DiscordCacheManager
from onyx.onyxbot.discord.constants import CACHE_REFRESH_INTERVAL
from onyx.onyxbot.discord.handle_commands import handle_dm
from onyx.onyxbot.discord.handle_commands import handle_registration_command
from onyx.onyxbot.discord.handle_commands import handle_sync_channels_command
from onyx.onyxbot.discord.handle_message import process_chat_message
from onyx.onyxbot.discord.handle_message import should_respond
from onyx.onyxbot.discord.utils import get_bot_token
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxDiscordClient(commands.Bot):
    """Discord bot client with integrated cache, API client, and message handling.

    This client handles:
    - Guild registration via !register command
    - Message processing with persona-based responses
    - Thread context for conversation continuity
    - Multi-tenant support via cached API keys
    """

    def __init__(self, command_prefix: str = DISCORD_BOT_INVOKE_CHAR) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(command_prefix=command_prefix, intents=intents)

        self.ready = False
        self.cache = DiscordCacheManager()
        self.api_client = OnyxAPIClient()
        self._cache_refresh_task: asyncio.Task | None = None

    # -------------------------------------------------------------------------
    # Lifecycle Methods
    # -------------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called before on_ready. Initialize components."""
        logger.info("Initializing Discord bot components...")

        # Initialize API client
        await self.api_client.initialize()

        # Initial cache load
        await self.cache.refresh_all()

        # Start periodic cache refresh
        self._cache_refresh_task = self.loop.create_task(self._periodic_cache_refresh())

        logger.info("Discord bot components initialized")

    async def _periodic_cache_refresh(self) -> None:
        """Background task to refresh cache periodically."""
        while not self.is_closed():
            await asyncio.sleep(CACHE_REFRESH_INTERVAL)
            try:
                await self.cache.refresh_all()
            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")

    async def on_ready(self) -> None:
        """Bot connected and ready."""
        if self.ready:
            return

        if not self.user:
            raise RuntimeError("Critical error: Discord Bot user not found")

        logger.info(f"Discord Bot connected as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info(f"Cached {len(self.cache.get_all_guild_ids())} registered guild(s)")

        self.ready = True

    async def close(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down Discord bot...")

        # Cancel cache refresh task
        if self._cache_refresh_task:
            self._cache_refresh_task.cancel()
            try:
                await self._cache_refresh_task
            except asyncio.CancelledError:
                pass

        # Close Discord connection first - stops new commands from triggering cache ops
        if not self.is_closed():
            await super().close()

        # Close API client
        await self.api_client.close()

        # Clear cache (safe now - no concurrent operations possible)
        self.cache.clear()

        self.ready = False
        logger.info("Discord bot shutdown complete")

    # -------------------------------------------------------------------------
    # Message Handling
    # -------------------------------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        """Main message handler."""
        # mypy
        if not self.user:
            raise RuntimeError("Critical error: Discord Bot user not found")

        try:
            # Ignore bot messages
            if message.author.bot:
                return

            # Ignore thread starter messages (empty reference nodes that don't contain content)
            if message.type == discord.MessageType.thread_starter_message:
                return

            # Handle DMs
            if isinstance(message.channel, discord.DMChannel):
                await handle_dm(message)
                return

            # Must have a guild
            if not message.guild or not message.guild.id:
                return

            guild_id = message.guild.id

            # Check for registration command first
            if await handle_registration_command(message, self.cache):
                return

            # Look up guild in cache
            tenant_id = self.cache.get_tenant(guild_id)

            # Check for sync-channels command (requires registered guild)
            if await handle_sync_channels_command(message, tenant_id, self):
                return

            if not tenant_id:
                # Guild not registered, ignore
                return

            # Get API key
            api_key = self.cache.get_api_key(tenant_id)
            if not api_key:
                logger.warning(f"No API key cached for tenant {tenant_id}")
                return

            # Check if bot should respond
            should_respond_context = await should_respond(message, tenant_id, self.user)

            if not should_respond_context.should_respond:
                return

            logger.debug(
                f"Processing message: '{message.content[:50]}' in "
                f"#{getattr(message.channel, 'name', 'unknown')} ({message.guild.name}), "
                f"persona_id={should_respond_context.persona_id}"
            )

            # Process the message
            await process_chat_message(
                message=message,
                api_key=api_key,
                persona_id=should_respond_context.persona_id,
                thread_only_mode=should_respond_context.thread_only_mode,
                api_client=self.api_client,
                bot_user=self.user,
            )

        except Exception as e:
            logger.exception(f"Error processing message: {e}")


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for Discord bot."""
    from onyx.db.engine.sql_engine import SqlEngine
    from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

    logger.info("Starting Onyx Discord Bot...")

    # Initialize the database engine (required before any DB operations)
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    # Initialize EE features based on environment
    set_is_ee_based_on_env_variable()

    counter = 0
    while True:
        token = get_bot_token()
        if not token:
            if counter % 180 == 0:
                logger.info(
                    "Discord bot is dormant. Waiting for token configuration..."
                )
            counter += 1
            time.sleep(5)
            continue
        counter = 0
        bot = OnyxDiscordClient()

        try:
            # bot.run() handles SIGINT/SIGTERM and calls close() automatically
            bot.run(token)

        except Exception:
            logger.exception("Fatal error in Discord bot")
            raise


if __name__ == "__main__":
    main()
