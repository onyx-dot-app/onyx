import threading
import time
from collections.abc import Callable
from typing import Any

from cachetools import TTLCache

from onyx.configs import app_configs as _cfg
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.security_settings import load_overrides as _db_load_overrides
from onyx.db.security_settings import upsert_overrides as _db_upsert_overrides
from onyx.server.security.models import OPERATOR_LOCKED_FIELDS
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


# 10s TTL: short enough that admin saves propagate across processes within
# the worst-case window the brief allows; long enough that hot paths see
# nearly-pure cache hits in steady state.
_CACHE_TTL_SECONDS = 10.0


# Module-level cache & lock. Tests may swap the cache via the
# _install_cache_for_test seam below; default is a real TTLCache.
_CACHE_LOCK = threading.RLock()
_CACHE: TTLCache[str, SecuritySettings] = TTLCache(
    maxsize=10_000, ttl=_CACHE_TTL_SECONDS, timer=time.monotonic
)


def _install_cache_for_test(
    *, ttl: float, timer: Callable[[], float], maxsize: int = 10_000
) -> None:
    """Test seam. Swaps the module-level cache with one driven by a fake
    clock so TTL behavior can be exercised without freezegun. Production
    code never calls this.
    """
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = TTLCache(maxsize=maxsize, ttl=ttl, timer=timer)


def _build_env_defaults() -> SecuritySettings:
    """Build a SecuritySettings from the current env constants. Reads each
    attribute on the module at call time so tests can monkeypatch.
    """
    return SecuritySettings(
        user_directory_admin_only=_cfg.USER_DIRECTORY_ADMIN_ONLY,
        track_external_idp_expiry=_cfg.TRACK_EXTERNAL_IDP_EXPIRY,
        mask_credential_prefix=_cfg.MASK_CREDENTIAL_PREFIX,
        valid_email_domains=tuple(_cfg.VALID_EMAIL_DOMAINS),
        password_min_length=_cfg.PASSWORD_MIN_LENGTH,
        password_max_length=_cfg.PASSWORD_MAX_LENGTH,
        password_require_uppercase=_cfg.PASSWORD_REQUIRE_UPPERCASE,
        password_require_lowercase=_cfg.PASSWORD_REQUIRE_LOWERCASE,
        password_require_digit=_cfg.PASSWORD_REQUIRE_DIGIT,
        password_require_special_char=_cfg.PASSWORD_REQUIRE_SPECIAL_CHAR,
    )


def merge_with_env(overrides: SecuritySettingsOverrides) -> SecuritySettings:
    """Apply per-field env fallbacks. Explicit `is None` checks so 0/False
    overrides are preserved (no `or` fallback). In multi-tenant mode,
    operator-locked field overrides are ignored (env always wins) — this
    is belt-and-braces enforcement in addition to the API-layer rejection.
    """
    env = _build_env_defaults()
    locked = OPERATOR_LOCKED_FIELDS if MULTI_TENANT else frozenset()

    merged: dict[str, Any] = {}
    for name in SecuritySettings.model_fields:
        override_value = getattr(overrides, name, None)
        if name in locked or override_value is None:
            merged[name] = getattr(env, name)
        else:
            merged[name] = override_value
    # SecuritySettings types valid_email_domains as tuple; overrides as list.
    if isinstance(merged["valid_email_domains"], list):
        merged["valid_email_domains"] = tuple(merged["valid_email_domains"])
    return SecuritySettings(**merged)


def load_raw_overrides() -> SecuritySettingsOverrides:
    """Uncached read of the persisted overrides. Used by the PUT path inside
    the Redis lock; everyone else should use get_security_settings().

    Returns an empty overrides object (all-None) when no row exists for this
    tenant — the loader treats that as "all env defaults".
    """
    with get_session_with_current_tenant() as db_session:
        return _db_load_overrides(db_session)


def store_overrides(overrides: SecuritySettingsOverrides) -> None:
    """Persist overrides as the singleton row and invalidate the current
    tenant's local cache entry. Caller must hold the Redis lock.

    In multi-tenant mode, operator-locked fields are forced to ``None``
    before persistence — defense in depth against bypasses of the API check.
    """
    if MULTI_TENANT:
        overrides = overrides.model_copy(
            update={field: None for field in OPERATOR_LOCKED_FIELDS}
        )
    with get_session_with_current_tenant() as db_session:
        _db_upsert_overrides(db_session, overrides)
    invalidate_security_cache(_current_tenant_id_or_default())


def _current_tenant_id_or_default() -> str:
    """Return the tenant id from the contextvar or POSTGRES_DEFAULT_SCHEMA.

    Inspects the contextvar directly (rather than calling
    get_current_tenant_id()) to avoid the stack-traced RuntimeError that
    function raises in multi-tenant when the contextvar is unset. Hot
    paths like /auth/type call into the loader before tenant resolution.
    """
    tid = CURRENT_TENANT_ID_CONTEXTVAR.get()
    return tid if tid is not None else POSTGRES_DEFAULT_SCHEMA


def invalidate_security_cache(tenant_id: str) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(tenant_id, None)


def get_security_settings() -> SecuritySettings:
    """Effective, env-merged, immutable settings for the current tenant.

    - Cache hit: process-local memory access (TTLCache under an RLock), no IO.
    - Cache miss: one sync DB roundtrip held under the same lock. Other
      tenants briefly block, but each tenant misses ≤1×/TTL/process so the
      contention is rare and the DB roundtrip is cheap.
    - Pre-tenant safe: when the tenant contextvar is unset in multi-tenant,
      returns a fresh env-defaults SecuritySettings (never cached) without
      touching the DB. Avoids the stack-trace cost of get_current_tenant_id()'s
      RuntimeError on hot unauth paths like /auth/type.
    - Result is frozen; callers cannot mutate the cached value.
    """
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        # MULTI_TENANT=true and contextvar not yet set (pre-tenant). Single-
        # tenant deployments default the contextvar to POSTGRES_DEFAULT_SCHEMA
        # at module import, so this branch only fires in multi-tenant.
        return _build_env_defaults()

    with _CACHE_LOCK:
        cached = _CACHE.get(tenant_id)
        if cached is not None:
            return cached
        try:
            effective = merge_with_env(load_raw_overrides())
        except Exception as e:
            # Never brick the auth path on a DB outage.
            logger.error("Failed to load security settings, using env defaults: %s", e)
            return _build_env_defaults()
        _CACHE[tenant_id] = effective
        return effective
