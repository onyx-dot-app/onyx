"""Shared multi-tenant cache for bot entity-tenant mappings and API keys.

Subclass ``BotCacheManager`` and implement the three abstract helpers to
create a platform-specific cache (e.g. Discord guilds, Teams teams).
"""

import asyncio
from abc import ABC
from abc import abstractmethod
from typing import Generic
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.onyxbot.exceptions import CacheError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

EntityIdT = TypeVar("EntityIdT")


class BotCacheManager(ABC, Generic[EntityIdT]):
    """Caches entity->tenant mappings and tenant->API key mappings.

    ``EntityIdT`` is ``int`` for Discord guilds, ``str`` for Teams teams.
    """

    def __init__(self, entity_name: str) -> None:
        self._entity_name = entity_name
        self._entity_tenants: dict[EntityIdT, str] = {}
        self._api_keys: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Abstract hooks — platform-specific DB access
    # ------------------------------------------------------------------

    @abstractmethod
    def _get_entity_ids(self, db: Session) -> list[EntityIdT]:
        """Return active entity IDs from DB configs."""

    @abstractmethod
    def _get_or_create_api_key(self, db: Session, tenant_id: str) -> str:
        """Provision (or retrieve) a service API key for *tenant_id*."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def refresh_all(self) -> None:
        """Full cache refresh from all tenants.

        Data is loaded outside the lock; the lock is only held for the
        atomic swap of the cache dicts so that ``refresh_entity`` and
        read operations are not blocked during I/O.
        """
        logger.info(f"Starting {self._entity_name} cache refresh")

        new_entity_tenants: dict[EntityIdT, str] = {}
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
                    entity_ids, api_key = await self._load_tenant_data(tenant_id)
                    if not entity_ids:
                        logger.debug(
                            f"No {self._entity_name} found for tenant " f"{tenant_id}"
                        )
                        continue

                    if not api_key:
                        logger.warning(
                            f"Service API key missing for tenant that has "
                            f"registered {self._entity_name}. {tenant_id} "
                            f"will not be handled in this refresh cycle."
                        )
                        continue

                    for entity_id in entity_ids:
                        new_entity_tenants[entity_id] = tenant_id

                    new_api_keys[tenant_id] = api_key
                except (OperationalError, ConnectionError, OSError) as e:
                    logger.warning(f"Failed to refresh tenant {tenant_id}: {e}")
                finally:
                    CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

            # Atomic swap under lock
            async with self._lock:
                self._entity_tenants = new_entity_tenants
                self._api_keys = new_api_keys
                self._initialized = True

            logger.info(
                f"Cache refresh complete: "
                f"{len(new_entity_tenants)} {self._entity_name}, "
                f"{len(new_api_keys)} tenants"
            )

        except (OperationalError, ConnectionError, OSError) as e:
            logger.error(f"Cache refresh failed: {e}")
            raise CacheError(f"Failed to refresh cache: {e}") from e

    async def refresh_entity(self, entity_id: EntityIdT, tenant_id: str) -> None:
        """Add a single entity to cache after registration."""
        logger.info(
            f"Refreshing cache for {self._entity_name} entity "
            f"{entity_id} (tenant: {tenant_id})"
        )

        context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            entity_ids, api_key = await self._load_tenant_data(tenant_id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

        async with self._lock:
            if entity_id in entity_ids:
                self._entity_tenants[entity_id] = tenant_id
                if api_key:
                    self._api_keys[tenant_id] = api_key
                logger.info(f"Cache updated for entity {entity_id}")
            else:
                logger.warning(f"Entity {entity_id} not found or disabled")

    def get_tenant(self, entity_id: EntityIdT) -> str | None:
        """Get tenant ID for an entity."""
        return self._entity_tenants.get(entity_id)

    def get_api_key(self, tenant_id: str) -> str | None:
        """Get API key for a tenant."""
        return self._api_keys.get(tenant_id)

    def remove_entity(self, entity_id: EntityIdT) -> None:
        """Remove an entity from cache."""
        self._entity_tenants.pop(entity_id, None)

    def get_all_entity_ids(self) -> list[EntityIdT]:
        """Get all cached entity IDs."""
        return list(self._entity_tenants.keys())

    def clear(self) -> None:
        """Clear all caches."""
        self._entity_tenants.clear()
        self._api_keys.clear()
        self._initialized = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _load_tenant_data(
        self, tenant_id: str
    ) -> tuple[list[EntityIdT], str | None]:
        """Load entity IDs and provision API key if needed."""
        cached_key = self._api_keys.get(tenant_id)

        def _sync() -> tuple[list[EntityIdT], str | None]:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                entity_ids = self._get_entity_ids(db)

                if not entity_ids:
                    return [], None

                if not cached_key:
                    new_key = self._get_or_create_api_key(db, tenant_id)
                    db.commit()
                    return entity_ids, new_key

                return entity_ids, cached_key

        return await asyncio.to_thread(_sync)
