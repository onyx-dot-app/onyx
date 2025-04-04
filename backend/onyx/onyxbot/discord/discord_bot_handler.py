import asyncio
import os
import signal
import sys
import threading
import time
from threading import Event
from types import FrameType
from typing import Dict
from typing import Set

import discord
from discord.ext import commands
from prometheus_client import Gauge
from prometheus_client import start_http_server
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISALLOWED_SLACK_BOT_TENANT_LIST
from onyx.configs.app_configs import POD_NAME
from onyx.configs.app_configs import POD_NAMESPACE
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine import get_all_tenant_ids
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import DiscordBot
from onyx.db.models import DiscordChannelConfig
from onyx.onyxbot.discord.config import MAX_TENANTS_PER_POD
from onyx.onyxbot.discord.config import TENANT_ACQUISITION_INTERVAL
from onyx.onyxbot.discord.config import TENANT_HEARTBEAT_EXPIRATION
from onyx.onyxbot.discord.config import TENANT_HEARTBEAT_INTERVAL
from onyx.onyxbot.discord.config import TENANT_LOCK_EXPIRATION
from onyx.onyxbot.discord.process_event import build_message_info
from onyx.onyxbot.discord.process_event import process_message
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

active_tenants_gauge = Gauge(
    "active_tenants",
    "Number of active tenants handled by this pod",
    ["namespace", "pod"],
)


class OnyxDiscordBot(commands.Bot):
    def __init__(
        self,
        discord_bot_id: int,
        tenant_id: str | None,
        command_prefix: str = "!",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=command_prefix,
            intents=intents,
        )

        self.discord_bot_id = discord_bot_id
        self.tenant_id = tenant_id
        self.ready = False
        self.setup_events()

    def setup_events(self) -> None:
        @self.event
        async def on_ready() -> None:
            if self.ready:
                return

            logger.info(
                f"Bot {self.discord_bot_id} connected as {self.user} "
                f"for tenant {self.tenant_id}"
            )
            self.ready = True

        @self.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self.user:
                return

            try:
                logger.info(f"Processing message with tenant: {self.tenant_id}")
                CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)

                # Get channel configuration first
                channel_config = None
                if not isinstance(message.channel, discord.DMChannel) and message.guild:
                    with get_session_with_tenant(self.tenant_id) as db_session:
                        from onyx.onyxbot.discord.config import (
                            get_discord_channel_config_for_bot_and_channel,
                        )

                        channel_config = get_discord_channel_config_for_bot_and_channel(
                            db_session=db_session,
                            discord_bot_id=self.discord_bot_id,
                            channel_name=message.channel.name,
                        )

                # Check if the bot should respond to this message
                if not self.should_respond(message, channel_config):
                    logger.info(
                        "Bot should not respond to this message based on configuration"
                    )
                    return

                # If we should respond, build the message info and process
                message_info = build_message_info(message=message, bot=self)
                logger.info(f"Built message info: {message_info}")
                await process_message(message, message_info, self)
            except Exception as e:
                logger.exception(f"Error in on_message: {e}")
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.set(None)

    def should_respond(
        self, message: discord.Message, channel_config: DiscordChannelConfig | None
    ) -> bool:
        if isinstance(message.channel, discord.DMChannel):
            return True

        if not channel_config:
            return self.user in message.mentions

        config = channel_config.channel_config

        # Check if we should respond to bots
        if message.author.bot and not config.get("respond_to_bots", False):
            return False

        # Check if we should only respond to mentions
        if config.get("respond_mention_only", False):
            return self.user in message.mentions

        # Check role permissions
        allowed_roles = config.get("allowed_role_ids", [])
        if allowed_roles:
            user_roles = [str(role.id) for role in message.author.roles]
            return any(role_id in allowed_roles for role_id in user_roles)

        return True

    async def close(self) -> None:
        try:
            if not self.is_closed():
                await super().close()
                logger.info(
                    f"Closed bot {self.discord_bot_id} connection "
                    f"for tenant {self.tenant_id}"
                )
        except Exception as e:
            logger.error(f"Error closing bot connection: {e}")


class DiscordbotHandler:
    def __init__(self) -> None:
        self.tenant_ids: Set[str | None] = set()
        self.discord_clients: Dict[tuple[str | None, int], OnyxDiscordBot] = {}
        self.running = True
        self.pod_id = self.get_pod_id()
        self._shutdown_event = Event()

        # Start background threads for tenant management
        self.acquire_thread = threading.Thread(
            target=self.acquire_tenants_loop, daemon=True
        )
        self.heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop, daemon=True
        )

        self.acquire_thread.start()
        self.heartbeat_thread.start()

        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        start_http_server(8000)

    def get_pod_id(self) -> str:
        return os.environ.get("HOSTNAME", "unknown_pod")

    def acquire_tenants_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                self.acquire_tenants()
                active_tenants_gauge.labels(namespace=POD_NAMESPACE, pod=POD_NAME).set(
                    len(self.tenant_ids)
                )
            except Exception as e:
                logger.exception(f"Error in Discord acquisition: {e}")
            self._shutdown_event.wait(timeout=TENANT_ACQUISITION_INTERVAL)

    def acquire_tenants(self) -> None:
        tenant_ids = get_all_tenant_ids()

        for tenant_id in tenant_ids:
            current_tenant = tenant_id or POSTGRES_DEFAULT_SCHEMA
            logger.info(f"Processing tenant: {current_tenant}")

            if (
                DISALLOWED_SLACK_BOT_TENANT_LIST is not None
                and current_tenant in DISALLOWED_SLACK_BOT_TENANT_LIST
            ):
                logger.info(
                    f"Tenant {current_tenant} is in the disallowed list, skipping"
                )
                continue

            if current_tenant in self.tenant_ids:
                logger.info(f"Tenant {current_tenant} already acquired")
                continue

            if len(self.tenant_ids) >= MAX_TENANTS_PER_POD:
                logger.info("Max tenants per pod reached")
                break

            try:
                redis_client = get_redis_client(tenant_id=current_tenant)
                logger.info(f"Got Redis client for tenant {current_tenant}")

                try:
                    acquired = redis_client.set(
                        OnyxRedisLocks.DISCORD_BOT_LOCK,
                        self.pod_id,
                        nx=True,
                        ex=TENANT_LOCK_EXPIRATION,
                    )

                    if acquired is None:
                        logger.warning(
                            f"Redis lock operation failed for {current_tenant}, skipping tenant"
                        )
                        continue  # Skip this tenant if Redis operation failed
                    elif acquired is False:
                        logger.info(
                            f"Another pod holds the lock for tenant {current_tenant}"
                        )
                        continue

                except Exception as e:
                    logger.warning(
                        f"Redis error for {current_tenant}, skipping tenant: {e}"
                    )
                    continue  # Skip this tenant if there was a Redis error

                self.tenant_ids.add(current_tenant)

            except Exception as e:
                logger.exception(
                    f"Error in tenant acquisition process for {current_tenant}: {e}"
                )
                continue

        for tenant_id in self.tenant_ids:
            current_tenant = tenant_id or POSTGRES_DEFAULT_SCHEMA
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(current_tenant)
            try:
                with get_session_with_tenant(current_tenant) as db_session:
                    try:
                        bots = (
                            db_session.query(DiscordBot)
                            .filter(DiscordBot.enabled.is_(True))
                            .all()
                        )
                        for bot in bots:
                            self._manage_discord_clients(
                                db_session=db_session,
                                tenant_id=current_tenant,
                                bot=bot,
                            )
                    except Exception as e:
                        logger.exception(
                            f"Error initializing bots for tenant {current_tenant}: {e}"
                        )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    def _manage_discord_clients(
        self, db_session: Session, tenant_id: str | None, bot: DiscordBot
    ) -> None:
        bot_key = (tenant_id, bot.id)

        # If bot is disabled or token not set, close existing client
        if not bot.enabled or not bot.discord_bot_token:
            if bot_key in self.discord_clients:
                asyncio.run(self.discord_clients[bot_key].close())
                del self.discord_clients[bot_key]
            return

        # Check if bot exists and token changed
        client_exists = bot_key in self.discord_clients
        if client_exists:
            existing_bot = self.discord_clients[bot_key]
            if existing_bot.discord_bot_token != bot.discord_bot_token:
                # Token changed, restart bot
                asyncio.run(existing_bot.close())
                asyncio.run(self.start_bot(bot.id, tenant_id, bot.discord_bot_token))
        else:
            asyncio.run(self.start_bot(bot.id, tenant_id, bot.discord_bot_token))

    async def start_bot(self, bot_id: int, tenant_id: str | None, token: str) -> None:
        bot_key = (tenant_id, bot_id)
        if bot_key in self.discord_clients:
            await self.discord_clients[bot_key].close()

        bot = OnyxDiscordBot(discord_bot_id=bot_id, tenant_id=tenant_id)
        try:
            await bot.start(token)
            self.discord_clients[bot_key] = bot
            logger.info(f"Started bot {bot_id} for tenant {tenant_id}")
        except Exception as e:
            logger.error(f"Failed to start bot {bot_id}: {e}")
            raise

    def heartbeat_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                self.send_heartbeats()
                logger.debug(f"Sent heartbeats for {len(self.tenant_ids)} tenants")
            except Exception as e:
                logger.exception(f"Error in heartbeat loop: {e}")
            self._shutdown_event.wait(timeout=TENANT_HEARTBEAT_INTERVAL)

    def send_heartbeats(self) -> None:
        current_time = int(time.time())
        for tenant_id in self.tenant_ids:
            redis_client = get_redis_client(tenant_id=tenant_id)
            heartbeat_key = (
                f"{OnyxRedisLocks.DISCORD_BOT_HEARTBEAT_PREFIX}:{self.pod_id}"
            )
            redis_client.set(
                heartbeat_key, current_time, ex=TENANT_HEARTBEAT_EXPIRATION
            )

    def release_tenant(self, tenant_id: str | None) -> None:
        if tenant_id not in self.tenant_ids:
            return

        # Close all bots for this tenant
        tenant_bots = [
            (t_id, bot_id)
            for (t_id, bot_id) in self.discord_clients.keys()
            if t_id == tenant_id
        ]

        for bot_key in tenant_bots:
            if bot := self.discord_clients.get(bot_key):
                asyncio.run(bot.close())
            self.discord_clients.pop(bot_key, None)

        # Release Redis lock
        redis_client = get_redis_client(tenant_id=tenant_id)
        redis_client.delete(OnyxRedisLocks.DISCORD_BOT_LOCK)

        self.tenant_ids.remove(tenant_id)

    async def shutdown(
        self, signum: int | None = None, frame: FrameType | None = None
    ) -> None:
        if not self.running:
            return

        self.running = False
        self._shutdown_event.set()

        # Close all discord clients
        for (tenant_id, bot_id), client in self.discord_clients.items():
            try:
                await client.close()
                logger.info(
                    f"Closed Discord client for tenant: {tenant_id}, bot: {bot_id}"
                )
            except Exception as e:
                logger.error(f"Error closing Discord client: {e}")

        for tenant_id in list(self.tenant_ids):
            try:
                self.release_tenant(tenant_id)
            except Exception as e:
                logger.error(f"Error releasing tenant {tenant_id}: {e}")

        sys.exit(0)

    def run(self) -> None:
        try:
            while self.running:
                time.sleep(1)
        except Exception as e:
            logger.exception(f"Error in main loop: {e}")
        finally:
            asyncio.run(self.shutdown())
