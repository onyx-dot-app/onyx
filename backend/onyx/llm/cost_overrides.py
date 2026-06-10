"""Admin per-model cost overrides — negotiated enterprise rates that win over litellm."""

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ModelCostOverride
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# (input, output, cache_read | None) per-Mtok USD; null cache => bill at input.
_OverrideRates = tuple[float, float, float | None]

# Per-tenant snapshot of the override table, keyed by tenant_id: a shared
# process serves many tenants, so an unkeyed cache would bill one tenant's
# negotiated rates to all. A write invalidates only the writer's process, so
# the TTL bounds how long sibling workers serve stale rates after an admin edit.
_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
# Keyed by (provider, model) so the same model can carry per-provider rates;
# provider is "" for a provider-agnostic override.
_OverrideKey = tuple[str, str]
# tenant_id -> (loaded_at_monotonic, {(provider, model): rates})
_cache: dict[str, tuple[float, dict[_OverrideKey, _OverrideRates]]] = {}
# Bound the per-tenant cache so a many-tenant process can't accumulate entries
# unboundedly; evict the oldest (insertion order) when full.
_MAX_CACHED_TENANTS = 10_000


def _load_cache(db_session: Session) -> dict[_OverrideKey, _OverrideRates]:
    rows = db_session.execute(select(ModelCostOverride)).scalars().all()
    return {
        (r.provider, r.model): (
            r.input_cost_per_mtok,
            r.output_cost_per_mtok,
            r.cache_read_cost_per_mtok,
        )
        for r in rows
    }


def _lookup(
    snapshot: dict[_OverrideKey, _OverrideRates], model: str, provider: str
) -> _OverrideRates | None:
    # Prefer a provider-specific rate, else the provider-agnostic ("") one.
    return snapshot.get((provider, model)) or snapshot.get(("", model))


def get_override(
    db_session: Session, model: str, provider: str = ""
) -> _OverrideRates | None:
    """Return the (input, output, cache_read) rates for `model` (+ optional
    `provider`) in the current tenant, or None if unset."""
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        entry = _cache.get(tenant_id)
    if entry is not None and (time.monotonic() - entry[0]) < _CACHE_TTL_SECONDS:
        return _lookup(entry[1], model, provider)

    # Reload outside the lock so a slow DB query doesn't serialize every other
    # tenant's lookups. A concurrent double-load is harmless (idempotent).
    try:
        snapshot = _load_cache(db_session)
    except Exception:
        # Cost computation must never raise. On a transient load failure keep
        # serving the last good snapshot (stale rates beat silently dropping
        # negotiated rates); only with no prior snapshot do we treat as no
        # overrides. The stale timestamp is left as-is so the next lookup retries.
        logger.exception("Failed to load model cost overrides")
        return _lookup(entry[1], model, provider) if entry is not None else None

    entry = (time.monotonic(), snapshot)
    with _cache_lock:
        if tenant_id not in _cache and len(_cache) >= _MAX_CACHED_TENANTS:
            _cache.pop(next(iter(_cache)), None)
        _cache[tenant_id] = entry
    return _lookup(snapshot, model, provider)


def invalidate_override_cache() -> None:
    """Drop the current tenant's cached snapshot so its next lookup reloads."""
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        _cache.pop(tenant_id, None)


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
    """Set the negotiated rates for (`provider`, `model`), creating or replacing
    its row. `provider` is "" for a provider-agnostic override.

    Rates are USD per million tokens; a null cache rate bills cache reads at the
    input rate. Caller invalidates the cache and commits.
    """
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
