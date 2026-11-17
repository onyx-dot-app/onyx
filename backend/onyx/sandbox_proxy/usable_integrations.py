"""The integrations each sandbox owner can use, cached for a short time."""

import threading
from collections.abc import Callable, Hashable
from uuid import UUID

from cachetools import TTLCache

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.integrations.craft import UsableIntegrationIds, load_usable_integration_ids

CACHE_TTL_S = 30.0


class TTLMemo[K: Hashable, V]:
    def __init__(self, ttl_s: float) -> None:
        self._lock = threading.Lock()
        self._cache: TTLCache[K, V] = TTLCache(maxsize=10_000, ttl=ttl_s)

    def get(self, key: K, load: Callable[[], V]) -> V:
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        # Loaded outside the lock so a slow query does not stall other keys; a
        # concurrent duplicate load is harmless.
        value = load()
        with self._lock:
            self._cache[key] = value
        return value


class UsableIntegrations:
    def __init__(self, ttl_s: float = CACHE_TTL_S) -> None:
        self._memo: TTLMemo[tuple[str, UUID], UsableIntegrationIds] = TTLMemo(ttl_s)

    def get(self, tenant_id: str, user_id: UUID) -> UsableIntegrationIds:
        return self._memo.get(
            (tenant_id, user_id), lambda: self._load(tenant_id, user_id)
        )

    def _load(self, tenant_id: str, user_id: UUID) -> UsableIntegrationIds:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            return load_usable_integration_ids(db, user_id)
