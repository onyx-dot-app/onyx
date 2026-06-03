"""Admin per-model cost overrides — negotiated enterprise rates that win over litellm."""

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ModelCostOverride
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# (input_cost_per_mtok, output_cost_per_mtok) in USD per million tokens.
_OverrideRates = tuple[float, float]

# Per-tenant snapshot of the override table, keyed by tenant_id. Onyx is
# multi-tenant (one process serves many per-tenant schemas), so the cache MUST
# be tenant-scoped or one tenant's negotiated rates would be billed to all
# others. Mutations invalidate the writing tenant's entry only.
_cache_lock = threading.Lock()
_cache: dict[str, dict[str, _OverrideRates]] = {}


def _load_cache(db_session: Session) -> dict[str, _OverrideRates]:
    rows = db_session.execute(select(ModelCostOverride)).scalars().all()
    return {r.model: (r.input_cost_per_mtok, r.output_cost_per_mtok) for r in rows}


def get_override(db_session: Session, model: str) -> _OverrideRates | None:
    """Return (input_per_mtok, output_per_mtok) for `model` in the current
    tenant, or None if unset."""
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        tenant_cache = _cache.get(tenant_id)
        if tenant_cache is None:
            try:
                tenant_cache = _load_cache(db_session)
            except Exception:
                # Cost computation must never raise; treat as no overrides.
                logger.exception("Failed to load model cost overrides")
                return None
            _cache[tenant_id] = tenant_cache
        return tenant_cache.get(model)


def invalidate_override_cache() -> None:
    """Drop the current tenant's cached snapshot so its next lookup reloads."""
    tenant_id = get_current_tenant_id()
    with _cache_lock:
        _cache.pop(tenant_id, None)
