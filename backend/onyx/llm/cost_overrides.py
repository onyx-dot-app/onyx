"""Admin per-model cost overrides — negotiated enterprise rates that win over the model catalog."""

import threading
import time

from cachetools import LRUCache, TTLCache
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.db.cost_override import fetch_cost_overrides
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class CostOverrideRates(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cache_read_cost_per_mtok: float | None


_CACHE_TTL_SECONDS = 60.0
_MAX_CACHED_TENANTS = 10_000
_cache_lock = threading.Lock()
# Keyed by model configuration id.
_OverrideKey = int
# Process-local tenant snapshots; TTL bounds cross-worker staleness.
_cache: TTLCache[str, dict[_OverrideKey, CostOverrideRates]] = TTLCache(
    maxsize=_MAX_CACHED_TENANTS,
    ttl=_CACHE_TTL_SECONDS,
    timer=time.monotonic,
)
# Preserve the last valid snapshot when a refresh fails after TTL expiry.
_last_known_cache: LRUCache[str, dict[_OverrideKey, CostOverrideRates]] = LRUCache(
    maxsize=_MAX_CACHED_TENANTS
)
_cache_generation = 0


def _load_cache(db_session: Session) -> dict[_OverrideKey, CostOverrideRates]:
    return {
        r.model_configuration_id: CostOverrideRates(
            input_cost_per_mtok=r.input_cost_per_mtok,
            output_cost_per_mtok=r.output_cost_per_mtok,
            cache_read_cost_per_mtok=r.cache_read_cost_per_mtok,
        )
        for r in fetch_cost_overrides(db_session)
    }


def get_override(
    db_session: Session, model_configuration_id: int
) -> CostOverrideRates | None:
    """The configuration's negotiated rates, from a per-tenant snapshot."""
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        snapshot = _cache.get(tenant_id)
        last_known = _last_known_cache.get(tenant_id)
        generation = _cache_generation
    if snapshot is not None:
        return snapshot.get(model_configuration_id)

    # Reload outside lock — slow query must not block other tenants.
    try:
        snapshot = _load_cache(db_session)
    except Exception:
        logger.exception("Failed to load model cost overrides")
        return (
            last_known.get(model_configuration_id) if last_known is not None else None
        )

    with _cache_lock:
        stale = generation != _cache_generation
        if stale:
            current = _cache.get(tenant_id)
        else:
            current = None
            _cache[tenant_id] = snapshot
            _last_known_cache[tenant_id] = snapshot
    if stale:
        if current is not None:
            return current.get(model_configuration_id)
        return get_override(db_session, model_configuration_id)
    return snapshot.get(model_configuration_id)


def invalidate_override_cache() -> None:
    """Drop the current tenant's cached snapshot so its next lookup reloads."""
    global _cache_generation

    tenant_id = get_current_tenant_id()
    with _cache_lock:
        _cache_generation += 1
        _cache.pop(tenant_id, None)
        _last_known_cache.pop(tenant_id, None)
