"""Resolve a tenant to the physical database ("shard") holding its schema.

This sits on the request hot path, so it must not issue a catalog query per session.
Resolution order:

1. ``ONYX_DB_SHARD_OVERRIDES`` — static operator escape hatch, no I/O.
2. In-process TTL cache.
3. ``public.tenant_shard`` in the catalog database.
4. The default shard.

A tenant with no ``tenant_shard`` row lives on the default shard. That makes the table
empty until tenants are actually migrated, so no backfill is needed and an
unconfigured deployment never depends on it existing.

Failure of the catalog lookup degrades to the default shard rather than raising: with
a single shard configured that is always the right answer, and it means a catalog
hiccup cannot take down request handling for a deployment that isn't sharded yet.
"""

import json
import threading
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.configs.app_configs import (
    ONYX_DB_SHARD_MAP_TTL_SECONDS,
    ONYX_DB_SHARD_OVERRIDES_JSON,
)
from onyx.db.engine.shard_registry import (
    ShardConfigurationError,
    get_catalog_engine,
    get_default_shard_name,
    get_engine_for_shard,
    get_shard_specs,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _parse_overrides() -> dict[str, str]:
    if not ONYX_DB_SHARD_OVERRIDES_JSON:
        return {}
    try:
        raw = json.loads(ONYX_DB_SHARD_OVERRIDES_JSON)
    except json.JSONDecodeError as e:
        raise ShardConfigurationError(
            f"ONYX_DB_SHARD_OVERRIDES is not valid JSON: {e}"
        ) from e
    if not isinstance(raw, dict):
        raise ShardConfigurationError(
            "ONYX_DB_SHARD_OVERRIDES must be a JSON object of tenant_id -> shard name"
        )
    return {str(k): str(v) for k, v in raw.items()}


_OVERRIDES: dict[str, str] | None = None
_OVERRIDES_LOCK = threading.Lock()


def get_shard_overrides() -> dict[str, str]:
    global _OVERRIDES
    if _OVERRIDES is None:
        with _OVERRIDES_LOCK:
            if _OVERRIDES is None:
                _OVERRIDES = _parse_overrides()
                if _OVERRIDES:
                    logger.warning(
                        "ONYX_DB_SHARD_OVERRIDES active for %d tenant(s) — this bypasses "
                        "the tenant_shard catalog table",
                        len(_OVERRIDES),
                    )
    return _OVERRIDES


class _ShardCache:
    """tenant_id -> (shard_name, expires_at monotonic seconds)."""

    _entries: dict[str, tuple[str, float]] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls, tenant_id: str) -> str | None:
        entry = cls._entries.get(tenant_id)
        if entry is None:
            return None
        shard_name, expires_at = entry
        if time.monotonic() >= expires_at:
            return None
        return shard_name

    @classmethod
    def put(cls, tenant_id: str, shard_name: str) -> None:
        with cls._lock:
            cls._entries[tenant_id] = (
                shard_name,
                time.monotonic() + ONYX_DB_SHARD_MAP_TTL_SECONDS,
            )

    @classmethod
    def invalidate(cls, tenant_id: str | None = None) -> None:
        with cls._lock:
            if tenant_id is None:
                cls._entries = {}
            else:
                cls._entries.pop(tenant_id, None)


def invalidate_shard_cache(tenant_id: str | None = None) -> None:
    """Drop cached routing for one tenant, or all of them.

    Called by the tenant migrator immediately after flipping a `tenant_shard` row so
    this process picks the change up without waiting out the TTL.
    """
    _ShardCache.invalidate(tenant_id)


def reset_shard_overrides() -> None:
    """Re-read ONYX_DB_SHARD_OVERRIDES from configuration."""
    global _OVERRIDES
    with _OVERRIDES_LOCK:
        _OVERRIDES = None


def _lookup_shard_in_catalog(tenant_id: str) -> str | None:
    """Read `public.tenant_shard` from the catalog database.

    Returns None when the tenant has no row, or when the table does not exist yet
    (pre-migration deployments).
    """
    engine = get_catalog_engine()
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT shard_name FROM public.tenant_shard WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).first()
    except Exception:
        # Table missing (not yet migrated) or catalog unreachable. Either way the
        # default shard is the safe answer — see module docstring.
        logger.warning(
            "tenant_shard lookup failed for %s; falling back to default shard",
            tenant_id,
            exc_info=True,
        )
        return None

    if result is None:
        return None
    return str(result[0])


def get_shard_for_tenant(tenant_id: str) -> str:
    """Name of the shard holding this tenant's schema."""
    default_shard = get_default_shard_name()

    # Single-database deployments never consult the catalog.
    if not MULTI_TENANT or len(get_shard_specs()) == 1:
        return default_shard

    overrides = get_shard_overrides()
    if tenant_id in overrides:
        return overrides[tenant_id]

    cached = _ShardCache.get(tenant_id)
    if cached is not None:
        return cached

    shard_name = _lookup_shard_in_catalog(tenant_id) or default_shard
    if shard_name not in get_shard_specs():
        logger.error(
            "Tenant %s maps to unknown shard '%s'; falling back to default shard",
            tenant_id,
            shard_name,
        )
        shard_name = default_shard

    _ShardCache.put(tenant_id, shard_name)
    return shard_name


def get_engine_for_tenant(tenant_id: str) -> Engine:
    """Engine for the database holding this tenant's schema.

    With one shard configured this is the default engine, i.e. exactly the behavior
    Onyx has always had.
    """
    return get_engine_for_shard(get_shard_for_tenant(tenant_id))
