"""Multi-tenant cache for Discord bot guild-tenant mappings and API keys."""

import asyncio
from typing import NamedTuple

from onyx.db.discord_bot import get_guild_configs
from onyx.db.discord_bot import get_or_create_discord_service_api_key
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.onyxbot.discord.exceptions import CacheError
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# Bounded so a cluster with many tenants can't exhaust the DB connection pool.
_REFRESH_MAX_WORKERS = 16


class TenantDiscordData(NamedTuple):
    """A tenant's enabled guild IDs and its Discord service API key."""

    guild_ids: list[int]
    api_key: str | None


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

                tenant_ids = [
                    tenant_id
                    for tenant_id in await asyncio.to_thread(get_all_tenant_ids)
                    if tenant_id not in gated
                ]

                # Log failures with tenant_id here; the thread pool only knows the
                # positional index.
                def load(tenant_id: str) -> TenantDiscordData | None:
                    try:
                        return self._load_tenant_data(
                            tenant_id, self._api_keys.get(tenant_id)
                        )
                    except Exception:
                        logger.exception("Failed to refresh tenant %s", tenant_id)
                        return None

                # allow_failures so one tenant can't abort the batch, independent of
                # load()'s except clause.
                results: list[TenantDiscordData | None] = await asyncio.to_thread(
                    run_functions_tuples_in_parallel,
                    [(load, (tenant_id,)) for tenant_id in tenant_ids],
                    allow_failures=True,
                    max_workers=_REFRESH_MAX_WORKERS,
                )

                for tenant_id, result in zip(tenant_ids, results):
                    if result is None:
                        continue

                    guild_ids, api_key = result
                    if not guild_ids:
                        logger.debug("No guilds found for tenant %s", tenant_id)
                        continue

                    if not api_key:
                        logger.warning(
                            "Discord service API key missing for tenant that has registered guilds. %s will not be handled in this refresh cycle.",
                            tenant_id,
                        )
                        continue

                    for guild_id in guild_ids:
                        new_guild_tenants[guild_id] = tenant_id

                    new_api_keys[tenant_id] = api_key

                self._guild_tenants = new_guild_tenants
                self._api_keys = new_api_keys
                self._initialized = True

                logger.info(
                    "Cache refresh complete: %s guilds, %s tenants",
                    len(new_guild_tenants),
                    len(new_api_keys),
                )

            except Exception as e:
                logger.error("Cache refresh failed: %s", e)
                raise CacheError(f"Failed to refresh cache: {e}") from e

    async def refresh_guild(self, guild_id: int, tenant_id: str) -> None:
        """Add a single guild to cache after registration."""
        async with self._lock:
            logger.info(
                "Refreshing cache for guild %s (tenant: %s)", guild_id, tenant_id
            )

            guild_ids, api_key = await asyncio.to_thread(
                self._load_tenant_data, tenant_id, self._api_keys.get(tenant_id)
            )

            if guild_id in guild_ids:
                self._guild_tenants[guild_id] = tenant_id
                if api_key:
                    self._api_keys[tenant_id] = api_key
                logger.info("Cache updated for guild %s", guild_id)
            else:
                logger.warning("Guild %s not found or disabled", guild_id)

    @staticmethod
    def _load_tenant_data(tenant_id: str, cached_key: str | None) -> TenantDiscordData:
        """Load a tenant's enabled guilds and provision an API key if needed.

        Synchronous so it can run in a worker thread (via to_thread / the parallel
        refresh). Sets the tenant contextvar so downstream calls that rely on it
        resolve the correct tenant; the surrounding copied context keeps this
        isolated from other concurrent workers.

        api_key is the cached key if available, otherwise a newly created one.
        guild_ids is empty if none are found.
        """
        context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                configs = get_guild_configs(db)
                guild_ids = [
                    config.guild_id
                    for config in configs
                    if config.enabled and config.guild_id is not None
                ]

                if not guild_ids:
                    return TenantDiscordData([], None)

                if not cached_key:
                    new_key = get_or_create_discord_service_api_key(db, tenant_id)
                    db.commit()
                    return TenantDiscordData(guild_ids, new_key)

                return TenantDiscordData(guild_ids, cached_key)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

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
