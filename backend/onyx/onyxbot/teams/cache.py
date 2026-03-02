"""Multi-tenant cache for Teams bot team-tenant mappings and API keys."""

from sqlalchemy.orm import Session

from onyx.db.teams_bot import get_or_create_teams_service_api_key
from onyx.db.teams_bot import get_team_configs
from onyx.onyxbot.cache import BotCacheManager


class TeamsCacheManager(BotCacheManager[str]):
    """Caches team->tenant mappings and tenant->API key mappings."""

    def __init__(self) -> None:
        super().__init__(entity_name="teams")

    def _get_entity_ids(self, db: Session) -> list[str]:
        configs = get_team_configs(db)
        return [
            config.team_id
            for config in configs
            if config.enabled and config.team_id is not None
        ]

    def _get_or_create_api_key(self, db: Session, tenant_id: str) -> str:
        return get_or_create_teams_service_api_key(db, tenant_id)

    # Convenience aliases for caller clarity
    async def refresh_team(self, team_id: str, tenant_id: str) -> None:
        await self.refresh_entity(team_id, tenant_id)

    def remove_team(self, team_id: str) -> None:
        self.remove_entity(team_id)

    def get_all_team_ids(self) -> list[str]:
        return self.get_all_entity_ids()
