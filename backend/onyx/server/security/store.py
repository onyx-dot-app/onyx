import threading
import time
from collections.abc import Callable
from typing import Any

from cachetools import TTLCache

from onyx.configs import app_configs as _cfg
from onyx.configs.constants import KV_SECURITY_SETTINGS_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


# Fields that, in multi-tenant deployments, can only be set by the operator
# via environment variables. Tenant admins cannot override them at runtime.
OPERATOR_LOCKED_FIELDS: frozenset[str] = frozenset(
    {
        "password_min_length",
        "password_max_length",
        "password_require_uppercase",
        "password_require_lowercase",
        "password_require_digit",
        "password_require_special_char",
        "valid_email_domains",
        "mask_credential_prefix",
    }
)


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


def is_multi_tenant() -> bool:
    # Read lazily so tests can monkeypatch the import-time binding inside
    # shared_configs.contextvars (which is what get_current_tenant_id uses).
    from shared_configs import contextvars as _ctx

    return bool(_ctx.MULTI_TENANT)


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
    locked = OPERATOR_LOCKED_FIELDS if is_multi_tenant() else frozenset()

    def pick(field: str, override_value: Any, env_value: Any) -> Any:
        if field in locked:
            return env_value
        return env_value if override_value is None else override_value

    return SecuritySettings(
        user_directory_admin_only=pick(
            "user_directory_admin_only",
            overrides.user_directory_admin_only,
            env.user_directory_admin_only,
        ),
        track_external_idp_expiry=pick(
            "track_external_idp_expiry",
            overrides.track_external_idp_expiry,
            env.track_external_idp_expiry,
        ),
        mask_credential_prefix=pick(
            "mask_credential_prefix",
            overrides.mask_credential_prefix,
            env.mask_credential_prefix,
        ),
        valid_email_domains=(
            env.valid_email_domains
            if "valid_email_domains" in locked or overrides.valid_email_domains is None
            else tuple(overrides.valid_email_domains)
        ),
        password_min_length=pick(
            "password_min_length",
            overrides.password_min_length,
            env.password_min_length,
        ),
        password_max_length=pick(
            "password_max_length",
            overrides.password_max_length,
            env.password_max_length,
        ),
        password_require_uppercase=pick(
            "password_require_uppercase",
            overrides.password_require_uppercase,
            env.password_require_uppercase,
        ),
        password_require_lowercase=pick(
            "password_require_lowercase",
            overrides.password_require_lowercase,
            env.password_require_lowercase,
        ),
        password_require_digit=pick(
            "password_require_digit",
            overrides.password_require_digit,
            env.password_require_digit,
        ),
        password_require_special_char=pick(
            "password_require_special_char",
            overrides.password_require_special_char,
            env.password_require_special_char,
        ),
    )


def load_raw_overrides() -> SecuritySettingsOverrides:
    """Uncached read of the raw KV blob. Used by the PUT path inside the
    Redis lock; everyone else should use get_security_settings().
    """
    kv = get_kv_store()
    try:
        stored = kv.load(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        return SecuritySettingsOverrides()
    if not stored:
        return SecuritySettingsOverrides()
    try:
        return SecuritySettingsOverrides.model_validate(stored)
    except Exception as e:
        logger.error("Invalid security overrides blob in KV: %s", e)
        return SecuritySettingsOverrides()


def store_overrides(overrides: SecuritySettingsOverrides) -> None:
    """Persist overrides to KV (absent fields stay absent via exclude_none)
    and invalidate the current tenant's local cache entry. Caller must
    hold the Redis lock.

    In multi-tenant mode, operator-locked fields are stripped before
    persistence — defense in depth against bypasses of the API check.
    """
    payload = overrides.model_dump(exclude_none=True)
    if is_multi_tenant():
        for field in OPERATOR_LOCKED_FIELDS:
            payload.pop(field, None)
    get_kv_store().store(KV_SECURITY_SETTINGS_KEY, payload)
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
    - Cache miss: one sync KV roundtrip via get_kv_store().load(...).
    - Pre-tenant safe: when the tenant contextvar is unset in multi-tenant,
      returns a fresh env-defaults SecuritySettings (never cached) without
      touching KV. Avoids the stack-trace cost of get_current_tenant_id()'s
      RuntimeError on hot unauth paths like /auth/type.
    - Thread-safe via an RLock around the TTLCache.
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
        overrides = load_raw_overrides()
        effective = merge_with_env(overrides)
    except Exception as e:
        # Never brick the auth path on a KV outage.
        logger.error("Failed to load security settings, using env defaults: %s", e)
        return _build_env_defaults()

    with _CACHE_LOCK:
        _CACHE[tenant_id] = effective
    return effective
