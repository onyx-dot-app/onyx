"""Multi-tenant cache for Discord bot guild-tenant mappings and API keys."""

import asyncio

from onyx.db.discord_bot import get_guild_configs
from onyx.db.discord_bot import get_or_create_discord_service_api_key
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.onyxbot.discord.exceptions import CacheError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class DiscordCacheManager:
    """Caches guild->tenant mappings and tenant->API key mappings.

    Refreshed on startup, periodically (every 60s), and when guilds register.
    """

    def __init__(self) -> None:
        self._guild_tenants: dict[int, str] = {}  # guild_id -> tenant_id
        self._api_keys: dict[str, str] = {}  # tenant_id -> api_key
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def refresh_all(self) -> None:
        """Full cache refresh from all tenants."""
        async with self._lock:
            logger.info("Starting Discord cache refresh")

            new_guild_tenants: dict[int, str] = {}
            new_api_keys: dict[str, str] = {}

            try:
                gated = fetch_ee_implementation_or_noop(
                    "onyx.server.tenants.product_gating",
                    "get_gated_tenants",
                    set(),
                )()

                tenant_ids = await asyncio.to_thread(get_all_tenant_ids)
                for tenant_id in tenant_ids:
                    if tenant_id in gated:
                        continue

                    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
                    try:
                        guild_ids, api_key = await self._load_tenant_data(tenant_id)
                        if not guild_ids:
                            logger.debug(f"No guilds found for tenant {tenant_id}")
                            continue

                        if not api_key:
                            logger.warning(
                                "Discord service API key missing for tenant that has registered guilds. "
                                f"{tenant_id} will not be handled in this refresh cycle."
                            )
                            continue

                        for guild_id in guild_ids:
                            new_guild_tenants[guild_id] = tenant_id

                        new_api_keys[tenant_id] = api_key
                    except Exception as e:
                        logger.warning(f"Failed to refresh tenant {tenant_id}: {e}")
                    finally:
                        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

                self._guild_tenants = new_guild_tenants
                self._api_keys = new_api_keys
                self._initialized = True

                logger.info(
                    f"Cache refresh complete: {len(new_guild_tenants)} guilds, "
                    f"{len(new_api_keys)} tenants"
                )

            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")
                raise CacheError(f"Failed to refresh cache: {e}") from e

    async def refresh_guild(self, guild_id: int, tenant_id: str) -> None:
        """Add a single guild to cache after registration."""
        async with self._lock:
            logger.info(f"Refreshing cache for guild {guild_id} (tenant: {tenant_id})")

            guild_ids, api_key = await self._load_tenant_data(tenant_id)

            if guild_id in guild_ids:
                self._guild_tenants[guild_id] = tenant_id
                if api_key:
                    self._api_keys[tenant_id] = api_key
                logger.info(f"Cache updated for guild {guild_id}")
            else:
                logger.warning(f"Guild {guild_id} not found or disabled")

    async def _load_tenant_data(self, tenant_id: str) -> tuple[list[int], str | None]:
        """Load guild IDs and provision API key if needed.

        Returns:
            (active_guild_ids, api_key) - api_key is the cached key if available,
            otherwise a newly created key. Returns None if no guilds found.
        """
        cached_key = self._api_keys.get(tenant_id)

        def _sync() -> tuple[list[int], str | None]:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                configs = get_guild_configs(db)
                guild_ids = [
                    config.guild_id
                    for config in configs
                    if config.enabled and config.guild_id is not None
                ]

                if not guild_ids:
                    return [], None

                if not cached_key:
                    new_key = get_or_create_discord_service_api_key(db, tenant_id)
                    db.commit()
                    return guild_ids, new_key

                return guild_ids, cached_key

        return await asyncio.to_thread(_sync)

    def get_tenant(self, guild_id: int) -> str | None:
        """Get tenant ID for a guild."""
        return self._guild_tenants.get(guild_id)

    def get_api_key(self, tenant_id: str) -> str | None:
        """Get API key for a tenant."""
        return self._api_keys.get(tenant_id)

    def remove_guild(self, guild_id: int) -> None:
        """Remove a guild from cache."""
        self._guild_tenants.pop(guild_id, None)

    def get_all_guild_ids(self) -> list[int]:
        """Get all cached guild IDs."""
        return list(self._guild_tenants.keys())

    def clear(self) -> None:
        """Clear all caches."""
        self._guild_tenants.clear()
        self._api_keys.clear()
        self._initialized = False
