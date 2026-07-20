"""Admin per-model cost overrides — negotiated enterprise rates that win over litellm."""

import threading
import time

from cachetools import LRUCache
from cachetools import TTLCache
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ModelCostOverride
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
# Keyed by (provider, model) so the same model can carry per-provider rates;
# provider is "" for a provider-agnostic override.
_OverrideKey = tuple[str, str]
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
    rows = db_session.execute(select(ModelCostOverride)).scalars().all()
    return {
        (r.provider, r.model): CostOverrideRates(
            input_cost_per_mtok=r.input_cost_per_mtok,
            output_cost_per_mtok=r.output_cost_per_mtok,
            cache_read_cost_per_mtok=r.cache_read_cost_per_mtok,
        )
        for r in rows
    }


def _lookup(
    snapshot: dict[_OverrideKey, CostOverrideRates], model: str, provider: str
) -> CostOverrideRates | None:
    # Prefer a provider-specific rate, else the provider-agnostic ("") one.
    return snapshot.get((provider, model)) or snapshot.get(("", model))


def get_override(
    db_session: Session, model: str, provider: str = ""
) -> CostOverrideRates | None:
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        snapshot = _cache.get(tenant_id)
        last_known = _last_known_cache.get(tenant_id)
        generation = _cache_generation
    if snapshot is not None:
        return _lookup(snapshot, model, provider)

    # Reload outside lock — slow query must not block other tenants.
    try:
        snapshot = _load_cache(db_session)
    except Exception:
        logger.exception("Failed to load model cost overrides")
        return _lookup(last_known, model, provider) if last_known is not None else None

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
            return _lookup(current, model, provider)
        return get_override(db_session, model, provider)
    return _lookup(snapshot, model, provider)


def invalidate_override_cache() -> None:
    """Drop the current tenant's cached snapshot so its next lookup reloads."""
    global _cache_generation

    tenant_id = get_current_tenant_id()
    with _cache_lock:
        _cache_generation += 1
        _cache.pop(tenant_id, None)
        _last_known_cache.pop(tenant_id, None)


def list_overrides(db_session: Session) -> list[ModelCostOverride]:
    """All override rows for the current tenant, ordered by model name."""
    return list(
        db_session.execute(select(ModelCostOverride).order_by(ModelCostOverride.model))
        .scalars()
        .all()
    )


def upsert_override(
    db_session: Session,
    model: str,
    input_cost_per_mtok: float,
    output_cost_per_mtok: float,
    cache_read_cost_per_mtok: float | None = None,
    provider: str = "",
) -> ModelCostOverride:
    """Set negotiated USD/Mtok rates for (provider, model).
    Caller commits + invalidates cache."""
    # Defense in depth behind the request model's ge=0: a negative rate would
    # credit usage and corrupt budget enforcement.
    for rate in (input_cost_per_mtok, output_cost_per_mtok, cache_read_cost_per_mtok):
        if rate is not None and rate < 0:
            raise ValueError("cost override rates must be non-negative")

    row = db_session.execute(
        select(ModelCostOverride).where(
            ModelCostOverride.provider == provider,
            ModelCostOverride.model == model,
        )
    ).scalar_one_or_none()

    if row is None:
        row = ModelCostOverride(
            provider=provider,
            model=model,
            input_cost_per_mtok=input_cost_per_mtok,
            output_cost_per_mtok=output_cost_per_mtok,
            cache_read_cost_per_mtok=cache_read_cost_per_mtok,
        )
        db_session.add(row)
    else:
        row.input_cost_per_mtok = input_cost_per_mtok
        row.output_cost_per_mtok = output_cost_per_mtok
        row.cache_read_cost_per_mtok = cache_read_cost_per_mtok

    db_session.flush()
    return row


def delete_override(db_session: Session, model: str, provider: str = "") -> bool:
    """Remove the override for (`provider`, `model`); False if there was none."""
    row = db_session.execute(
        select(ModelCostOverride).where(
            ModelCostOverride.provider == provider,
            ModelCostOverride.model == model,
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    db_session.delete(row)
    db_session.flush()
    return True
