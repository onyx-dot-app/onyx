import threading
import time
from collections.abc import Callable
from typing import Any

from cachetools import TTLCache
from pydantic import ValidationError

from onyx.cache.factory import get_cache_backend
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackendType
from onyx.configs import app_configs as _cfg
from onyx.configs.app_configs import CACHE_BACKEND
from onyx.configs.constants import OnyxRedisChannels
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.security_settings import load_overrides as _db_load_overrides
from onyx.db.security_settings import upsert_overrides as _db_upsert_overrides
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import OPERATOR_LOCKED_FIELDS
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


# Cross-process propagation is via pub/sub (see the listener below); this long
# TTL is only a staleness bound for messages a process missed while reconnecting.
_CACHE_TTL_SECONDS = 3600.0


_CACHE_LOCK = threading.RLock()
_CACHE: TTLCache[str, SecuritySettings] = TTLCache(
    maxsize=10_000, ttl=_CACHE_TTL_SECONDS, timer=time.monotonic
)


# One listener daemon per process; the lock keeps racing starters to one thread.
_LISTENER_LOCK = threading.Lock()
_LISTENER_STARTED = False

# Capped exponential backoff so a Redis outage can't become a hot reconnect loop.
_LISTENER_RECONNECT_BASE_SECONDS = 5.0
_LISTENER_RECONNECT_MAX_SECONDS = 30.0
# A subscription that stayed up this long is treated as healthy, resetting the
# backoff. Settings changes are rare, so we can't key "healthy" on message receipt.
_LISTENER_HEALTHY_SECONDS = 60.0


# Lock lifetime; held during a single read+merge+write.
_WRITE_LOCK_LEASE_SECONDS = 30.0
# How long a competing writer waits before giving up with CONFLICT.
_WRITE_LOCK_WAIT_SECONDS = 10.0


def _install_cache_for_test(
    *, ttl: float, timer: Callable[[], float], maxsize: int = 10_000
) -> None:
    """Test seam for fake-clock TTL testing; production never calls this."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = TTLCache(maxsize=maxsize, ttl=ttl, timer=timer)


def _build_env_defaults() -> SecuritySettings:
    """Builds from env constants at call time so tests can monkeypatch them."""
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
    """Apply per-field env fallbacks. Explicit ``is None`` so 0/False overrides
    aren't dropped by a truthy fallback. In multi-tenant, operator-locked
    overrides are ignored (env wins) — belt-and-braces alongside the API
    rejection.
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


def _load_raw_overrides_unlocked() -> SecuritySettingsOverrides:
    """Uncached DB read. Read-consistency comes from the write path's lock;
    cache-miss readers may see a stale value bounded by the TTL.
    """
    with get_session_with_current_tenant() as db_session:
        return _db_load_overrides(db_session)


def _store_overrides_unlocked(overrides: SecuritySettingsOverrides) -> None:
    """DB upsert + local cache invalidate. ``apply_patch`` is the only caller,
    and only while holding the Redis write lock.

    In multi-tenant, operator-locked fields are forced to ``None`` before
    write — defense-in-depth if a future internal caller bypasses the API check.
    """
    if MULTI_TENANT:
        overrides = overrides.model_copy(
            update={field: None for field in OPERATOR_LOCKED_FIELDS}
        )
    with get_session_with_current_tenant() as db_session:
        _db_upsert_overrides(db_session, overrides)
    tenant_id = _current_tenant_id_or_default()
    # Local invalidate is this process' fast path; pub/sub reaches the rest. The
    # DB write already committed, so neither may fail the save.
    invalidate_security_cache(tenant_id)
    _publish_invalidation(tenant_id)


def _apply_present_keys(
    existing: SecuritySettingsOverrides,
    patch: SecuritySettingsOverrides,
    present_keys: set[str],
) -> SecuritySettingsOverrides:
    """PATCH-semantic merge. Caller must pass ``present_keys`` so we can tell
    absent (keep existing) from explicit-null (clear → env fallback) — Pydantic
    collapses both to ``None`` on the parsed model.
    """
    merged: dict[str, Any] = existing.model_dump()
    for name in present_keys:
        merged[name] = getattr(patch, name, None)
    return SecuritySettingsOverrides.model_validate(merged)


def apply_patch(
    patch: SecuritySettingsOverrides, present_keys: set[str]
) -> SecuritySettings:
    """Public write entry point. Acquires the Redis lock for the full
    read-modify-write so concurrent writers can't clobber each other.

    Raises ``OnyxError(CONFLICT)`` if a competing writer holds the lock past
    the wait window, and ``OnyxError(INVALID_INPUT)`` if the merged effective
    state would violate a model invariant.
    """
    cache = get_cache_backend()
    lock = cache.lock(
        OnyxRedisLocks.SECURITY_SETTINGS, timeout=_WRITE_LOCK_LEASE_SECONDS
    )
    if not lock.acquire(blocking=True, blocking_timeout=_WRITE_LOCK_WAIT_SECONDS):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Another security settings save is in progress, please retry.",
        )
    try:
        existing = _load_raw_overrides_unlocked()
        merged = _apply_present_keys(existing, patch, present_keys)
        try:
            # SecuritySettings invariants run via model_validator on construction.
            effective = merge_with_env(merged)
        except ValidationError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))
        _store_overrides_unlocked(merged)
        return effective
    finally:
        # Lease may have expired during the write; unconditional release would
        # raise LockNotOwnedError and mask a successful save as a 500.
        if lock.owned():
            lock.release()


def _current_tenant_id_or_default() -> str:
    """Tenant id from the contextvar, or ``POSTGRES_DEFAULT_SCHEMA`` if unset.

    Inspects the contextvar directly; ``get_current_tenant_id()`` raises a
    stack-traced ``RuntimeError`` in multi-tenant when unset, which is too
    expensive for hot pre-tenant paths like ``/auth/type``.
    """
    tid = CURRENT_TENANT_ID_CONTEXTVAR.get()
    return tid if tid is not None else POSTGRES_DEFAULT_SCHEMA


def invalidate_security_cache(tenant_id: str) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(tenant_id, None)


def _pubsub_supported() -> bool:
    """Pub/sub requires Redis. Postgres (Onyx Lite) is single-process, so it
    skips both publish and the listener and relies on local invalidation."""
    return CACHE_BACKEND == CacheBackendType.REDIS


def _publish_invalidation(tenant_id: str) -> None:
    """Best-effort broadcast to other processes. The DB write already committed
    and the local cache is already invalidated, so a failure is logged, never
    raised — other processes still converge via the TTL fallback."""
    if not _pubsub_supported():
        return
    try:
        cache = get_shared_cache_backend()
        cache.publish(OnyxRedisChannels.SECURITY_SETTINGS_INVALIDATE, tenant_id)
    except Exception:
        logger.exception("Failed to publish security settings invalidation")


def _handle_invalidation_message(data: bytes) -> None:
    """Drop the named tenant from this process' cache. The channel is global, so
    a message for a tenant we never cached is a harmless no-op pop."""
    try:
        tenant_id = data.decode()
    except Exception:
        logger.warning("Discarding undecodable security invalidation message")
        return
    invalidate_security_cache(tenant_id)


def _listen_for_invalidations() -> None:
    """Daemon loop: subscribe to the invalidation channel and apply each message
    to the local cache, reconnecting with backoff on error. Never returns."""
    backoff = _LISTENER_RECONNECT_BASE_SECONDS
    while True:
        connected_at = time.monotonic()
        try:
            cache = get_shared_cache_backend()
            for data in cache.subscribe(OnyxRedisChannels.SECURITY_SETTINGS_INVALIDATE):
                _handle_invalidation_message(data)
            # subscribe() returned without raising — treat as a disconnect.
            logger.warning("Security settings invalidation stream ended; reconnecting")
        except Exception:
            logger.exception("Security settings invalidation listener error")
        # Reset after a connection that stayed up a while; keep growing (capped)
        # only while connections fail fast, so a flapping Redis backs off but a
        # healthy-but-quiet one reconnects promptly.
        healthy = time.monotonic() - connected_at >= _LISTENER_HEALTHY_SECONDS
        if healthy:
            backoff = _LISTENER_RECONNECT_BASE_SECONDS
        time.sleep(backoff)
        if not healthy:
            backoff = min(backoff * 2, _LISTENER_RECONNECT_MAX_SECONDS)


def _ensure_listener_started() -> None:
    """Lazily start the per-process listener. Idempotent; a flag read after the
    first start."""
    global _LISTENER_STARTED
    if _LISTENER_STARTED or not _pubsub_supported():
        return
    with _LISTENER_LOCK:
        if _LISTENER_STARTED:
            return
        thread = threading.Thread(
            target=_listen_for_invalidations,
            name="security-settings-invalidation-listener",
            daemon=True,
        )
        thread.start()
        _LISTENER_STARTED = True


def get_security_settings() -> SecuritySettings:
    """Effective, env-merged, immutable settings for the current tenant.

    Pre-tenant safe: returns env defaults (uncached) when the contextvar is
    unset in multi-tenant. DB errors fall back to env defaults so a Postgres
    outage never bricks the auth path. Returned ``SecuritySettings`` is frozen.
    """
    # Start the cross-process invalidation listener on first use (idempotent).
    _ensure_listener_started()

    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        # Single-tenant defaults the contextvar at module import; this branch
        # fires only in multi-tenant before tenant resolution.
        return _build_env_defaults()

    # The DB read is held under _CACHE_LOCK on purpose: invalidate_security_cache
    # also takes this lock, so a concurrent write blocks until our fill completes
    # and then pops it — a reader can't resurrect a pre-write value past an
    # invalidation. Don't switch to read-outside-the-lock (double-checked) here;
    # that race is exactly what this cache exists to avoid. The error path
    # returns env defaults without caching so a transient DB blip can't pin them
    # for the (long) TTL.
    with _CACHE_LOCK:
        cached = _CACHE.get(tenant_id)
        if cached is not None:
            return cached
        try:
            effective = merge_with_env(_load_raw_overrides_unlocked())
        except Exception as e:
            logger.error("Failed to load security settings, using env defaults: %s", e)
            return _build_env_defaults()
        _CACHE[tenant_id] = effective
        return effective
