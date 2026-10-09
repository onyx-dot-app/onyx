"""Resolve a tenant to the physical database ("shard") holding its schema.

This sits on the request hot path, so it must not issue a catalog query per session.
Resolution order:

1. ``ONYX_DB_SHARD_OVERRIDES`` — static operator escape hatch, no I/O.
2. In-process TTL cache, invalidated across processes by the Redis version
   counter in ``shard_version``.
3. ``public.tenant_shard`` in the catalog database.
4. The default shard.

A tenant with no ``tenant_shard`` row lives on the default shard. That makes the table
empty until tenants are actually migrated, so no backfill is needed and an
unconfigured deployment never depends on it existing.

**Routing fails closed.** If the catalog can't be consulted, or names an unknown
shard, resolution raises instead of assuming the default — guessing "default" for an
already-migrated tenant would send its writes to the database it moved off. The one
exception is a missing ``tenant_shard`` table: nothing can be mapped, so the default
is the only possible answer.
"""

import json
import threading
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from onyx.configs.app_configs import (
    ONYX_DB_SHARD_MAP_TTL_SECONDS,
    ONYX_DB_SHARD_OVERRIDES_JSON,
)
from onyx.db.engine.shard_registry import (
    ShardConfigurationError,
    get_catalog_engine,
    get_default_shard_name,
    get_engine_for_shard,
    get_new_tenant_shard_name,
    get_shard_specs,
    is_sharded,
)
from onyx.db.engine.shard_version import poll_shard_map_version
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


class ShardLookupError(RuntimeError):
    """The catalog could not be consulted, so the tenant's shard is unknown."""


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


# Built once under the lock and never mutated in place, so readers need no lock.
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
    """Cache of tenant_id -> (shard_name, expiry).

    Entries record `_generation` as of when their lookup *started*; `invalidate()`
    bumps it. That lets an in-flight lookup discard a result the migrator has already
    superseded, instead of caching the pre-flip shard for a full TTL.
    """

    _entries: dict[str, tuple[str, float]] = {}
    _lock: threading.Lock = threading.Lock()
    _generation: int = 0

    @classmethod
    def generation(cls) -> int:
        return cls._generation

    @classmethod
    def get(cls, tenant_id: str) -> str | None:
        # Read without the lock: this is the hot path, a single dict read is atomic,
        # and `invalidate` rebinds `_entries` rather than emptying it in place.
        entry = cls._entries.get(tenant_id)
        if entry is None:
            return None
        shard_name, expires_at = entry
        if time.monotonic() >= expires_at:
            return None
        return shard_name

    @classmethod
    def put(cls, tenant_id: str, shard_name: str, generation: int) -> None:
        with cls._lock:
            if generation != cls._generation:
                # Invalidated while this lookup was in flight; drop the result.
                return
            cls._entries[tenant_id] = (
                shard_name,
                time.monotonic() + ONYX_DB_SHARD_MAP_TTL_SECONDS,
            )

    @classmethod
    def invalidate(cls, tenant_id: str | None = None) -> None:
        with cls._lock:
            cls._generation += 1
            if tenant_id is None:
                cls._entries = {}
            else:
                cls._entries.pop(tenant_id, None)


def invalidate_shard_cache(tenant_id: str | None = None) -> None:
    """Drop cached routing for one tenant, or all of them, *in this process only*.

    To invalidate fleet-wide — which is what a migrator flip requires — call
    ``shard_version.bump_shard_map_version`` instead.
    """
    _ShardCache.invalidate(tenant_id)


def reset_shard_overrides() -> None:
    """Re-read ONYX_DB_SHARD_OVERRIDES from configuration."""
    global _OVERRIDES
    with _OVERRIDES_LOCK:
        _OVERRIDES = None


def is_undefined_table(exc: BaseException) -> bool:
    """True only for 'public.tenant_shard does not exist'.

    Separating this from other failures is what makes the default-shard fallback safe:
    no table means nothing is mapped, whereas any other error means unknown.
    """
    if isinstance(exc, ProgrammingError):
        pgcode = getattr(  # ods: ignore[getattr]
            getattr(exc, "orig", None),  # ods: ignore[getattr]
            "pgcode",
            None,
        )
        # 42P01 = undefined_table
        return pgcode == "42P01"
    return False


def _lookup_shard_in_catalog(tenant_id: str) -> str | None:
    """Read `public.tenant_shard` from the catalog database.

    Returns None when the tenant has no row, or when the table has not been created
    yet. Raises `ShardLookupError` if the catalog cannot be consulted — the caller
    must not guess, because guessing "default" for a migrated tenant sends its writes
    to the database it was moved off.
    """
    try:
        # Inside the try: building the catalog engine can itself fail, and that is
        # the same "mapping unknown" situation as a failed query.
        engine = get_catalog_engine()
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT shard_name FROM public.tenant_shard WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).first()
    except Exception as e:
        if is_undefined_table(e):
            # Deployment has not run the catalog migration yet; nothing is mapped.
            return None
        logger.exception("tenant_shard lookup failed for %s", tenant_id)
        raise ShardLookupError(
            f"Could not resolve the shard for tenant {tenant_id}: {e}"
        ) from e

    if result is None:
        return None
    return str(result[0])


def get_shard_for_tenant(tenant_id: str) -> str:
    """Name of the shard holding this tenant's schema."""
    default_shard = get_default_shard_name()

    # Single-database deployments never consult the catalog.
    if not MULTI_TENANT or not is_sharded():
        return default_shard

    overrides = get_shard_overrides()
    if tenant_id in overrides:
        return overrides[tenant_id]

    # Throttled; drops every cached mapping when a migrator has published a flip.
    if poll_shard_map_version():
        _ShardCache.invalidate()

    cached = _ShardCache.get(tenant_id)
    if cached is not None:
        return cached

    # Captured before the lookup so a concurrent invalidation discards our result
    # rather than letting it overwrite fresher state.
    generation = _ShardCache.generation()

    shard_name = _lookup_shard_in_catalog(tenant_id) or default_shard
    if shard_name not in get_shard_specs():
        # A mapping pointing at a shard this process knows nothing about. Falling
        # back to the default would route a migrated tenant's writes to its old
        # database, so refuse instead.
        raise ShardConfigurationError(
            f"Tenant {tenant_id} maps to unknown shard '{shard_name}' "
            f"(configured: {sorted(get_shard_specs())})"
        )

    _ShardCache.put(tenant_id, shard_name, generation)
    return shard_name


def get_shard_for_new_tenant() -> str:
    """Shard a tenant being created right now should be placed on.

    A configuration decision, not a lookup: unlike `get_shard_for_tenant`, there is no
    catalog row to consult yet. Raises rather than defaulting on an unknown shard —
    silently placing a tenant elsewhere is what this is meant to prevent.
    """
    shard_name = get_new_tenant_shard_name()
    if shard_name not in get_shard_specs():
        raise ShardConfigurationError(
            f"ONYX_DB_NEW_TENANT_SHARD='{shard_name}' is not a configured shard "
            f"(known: {sorted(get_shard_specs())})"
        )
    return shard_name


def get_engine_for_tenant(tenant_id: str) -> Engine:
    """Engine for the database holding this tenant's schema.

    With one shard configured this is the default engine, i.e. exactly the behavior
    Onyx has always had.
    """
    return get_engine_for_shard(get_shard_for_tenant(tenant_id))
