"""Multi-tenant cache for Discord bot guild-tenant mappings and API keys."""

from sqlalchemy.orm import Session

from onyx.db.discord_bot import get_guild_configs
from onyx.db.discord_bot import get_or_create_discord_service_api_key
from onyx.onyxbot.cache import BotCacheManager


class DiscordCacheManager(BotCacheManager[int]):
    """Caches guild->tenant mappings and tenant->API key mappings."""

    def __init__(self) -> None:
        super().__init__(entity_name="guilds")

    def _get_entity_ids(self, db: Session) -> list[int]:
        configs = get_guild_configs(db)
        return [
            config.guild_id
            for config in configs
            if config.enabled and config.guild_id is not None
        ]

    def _get_or_create_api_key(self, db: Session, tenant_id: str) -> str:
        return get_or_create_discord_service_api_key(db, tenant_id)

    # Convenience aliases for backward compatibility with callers
    async def refresh_guild(self, guild_id: int, tenant_id: str) -> None:
        await self.refresh_entity(guild_id, tenant_id)

    def remove_guild(self, guild_id: int) -> None:
        self.remove_entity(guild_id)

    def get_all_guild_ids(self) -> list[int]:
        return self.get_all_entity_ids()
