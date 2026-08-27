import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from cachetools import TTLCache
from pydantic import ValidationError

from onyx.cache.factory import get_cache_backend
from onyx.configs import app_configs as _cfg
from onyx.configs.constants import KV_PASSWORD_AUTH_ENABLED_KEY, OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IncognitoRecordMode
from onyx.db.security_settings import load_overrides as _db_load_overrides
from onyx.db.security_settings import upsert_overrides as _db_upsert_overrides
from onyx.db.sso_provider import fetch_sso_providers
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security.models import (
    ENV_PINNED_FIELDS,
    OPERATOR_LOCKED_FIELDS,
    IncognitoAvailability,
    SecuritySettings,
    SecuritySettingsOverrides,
    SSRFProtectionLevel,
)
from onyx.utils.audit import AuditAction, AuditActor, AuditOutcome, emit_audit_event
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


# Bounds cross-process staleness after an admin save — no pub/sub today, so
# other api_server processes converge via TTL expiry.
_CACHE_TTL_SECONDS = 10.0


_CACHE_LOCK = threading.RLock()
_CACHE: TTLCache[str, SecuritySettings] = TTLCache(
    maxsize=10_000, ttl=_CACHE_TTL_SECONDS, timer=time.monotonic
)


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


def _derive_ssrf_level_from_env() -> SSRFProtectionLevel:
    """Seed the new admin "SSRF Protection" setting's default from the legacy
    per-path SSRF env vars so existing deployments keep their access without
    touching the new control. VALIDATE_LLM is reachable solely through the admin
    setting, never derived from env:

    - DISABLED               open_url validation off, or MCP loopback opt-in.
                             Only DISABLED reaches loopback / turns open_url off,
                             so honoring these preserves prior access.
    - ALLOW_PRIVATE_NETWORK  MCP allowed onto the private network without the
                             loopback opt-in — the legacy "private without
                             loopback" posture (MCP reaches RFC1918 hosts;
                             loopback stays blocked).
    - VALIDATE_ALL           otherwise — secure by default (every outbound path,
                             incl. the web connector, refuses private IPs).

    The web connector validates whenever the level is VALIDATE_ALL (the default);
    an operator who needs it to reach private IPs picks a lower level in the admin
    setting.
    """
    if not _cfg.OPEN_URL_VALIDATE_SSRF or _cfg.MCP_SERVER_ALLOW_LOOPBACK:
        return SSRFProtectionLevel.DISABLED
    if _cfg.MCP_SERVER_ALLOW_PRIVATE_NETWORK:
        return SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK
    return SSRFProtectionLevel.VALIDATE_ALL


def _build_env_defaults() -> SecuritySettings:
    """Builds from env constants at call time so tests can monkeypatch them."""
    return SecuritySettings(
        user_directory_admin_only=_cfg.USER_DIRECTORY_ADMIN_ONLY,
        track_external_idp_expiry=_cfg.TRACK_EXTERNAL_IDP_EXPIRY,
        # No env knob on purpose: incognito is off until an admin enables it.
        incognito_availability=IncognitoAvailability.OFF,
        incognito_record_mode=IncognitoRecordMode.USAGE_ONLY,
        ssrf_protection_level=_derive_ssrf_level_from_env(),
        mask_credential_prefix=_cfg.MASK_CREDENTIAL_PREFIX,
        llm_custom_config_env_injection=not MULTI_TENANT,
        valid_email_domains=tuple(_cfg.VALID_EMAIL_DOMAINS),
        password_min_length=_cfg.PASSWORD_MIN_LENGTH,
        password_max_length=_cfg.PASSWORD_MAX_LENGTH,
        password_require_uppercase=_cfg.PASSWORD_REQUIRE_UPPERCASE,
        password_require_lowercase=_cfg.PASSWORD_REQUIRE_LOWERCASE,
        password_require_digit=_cfg.PASSWORD_REQUIRE_DIGIT,
        password_require_special_char=_cfg.PASSWORD_REQUIRE_SPECIAL_CHAR,
        password_auth_enabled=True,
        jwt_public_key_url=_cfg.JWT_PUBLIC_KEY_URL,
        jwt_expected_audience=_cfg.JWT_EXPECTED_AUDIENCE,
        jwt_expected_issuer=_cfg.JWT_EXPECTED_ISSUER,
    )


def merge_with_env(overrides: SecuritySettingsOverrides) -> SecuritySettings:
    """Apply per-field env fallbacks. Explicit ``is None`` so 0/False overrides
    aren't dropped by a truthy fallback. In multi-tenant, operator-locked
    overrides are ignored (env wins) — belt-and-braces alongside the API
    rejection.
    """
    env_values = _build_env_defaults().model_dump()
    override_values = overrides.model_dump()
    locked = OPERATOR_LOCKED_FIELDS if MULTI_TENANT else frozenset()

    merged: dict[str, Any] = {}
    for name in SecuritySettings.model_fields:
        override_value = override_values.get(name)
        env_value = env_values[name]
        # The DB row is truth only under an unset env (the why lives on
        # _env_pinned).
        if name in ENV_PINNED_FIELDS and env_value is not None:
            merged[name] = env_value
        elif name in locked or override_value is None:
            merged[name] = env_value
        else:
            merged[name] = override_value
    # Process-wide env vars are a cross-tenant risk: force injection off on
    # multi-tenant no matter what any stored or env-derived value says.
    if MULTI_TENANT:
        merged["llm_custom_config_env_injection"] = False
    # SecuritySettings types valid_email_domains as tuple; overrides as list.
    if isinstance(merged["valid_email_domains"], list):
        merged["valid_email_domains"] = tuple(merged["valid_email_domains"])
    return SecuritySettings(**merged)


def _load_password_auth_override() -> bool | None:
    try:
        raw = get_kv_store().load(KV_PASSWORD_AUTH_ENABLED_KEY)
    except KvKeyNotFoundError:
        return None
    return raw if isinstance(raw, bool) else None


def _load_raw_overrides_unlocked() -> SecuritySettingsOverrides:
    """Uncached read: DB row overrides with the KV-backed override overlaid."""
    with get_session_with_current_tenant() as db_session:
        overrides = _db_load_overrides(db_session)
    return overrides.model_copy(
        update={"password_auth_enabled": _load_password_auth_override()}
    )


def _store_overrides_unlocked(overrides: SecuritySettingsOverrides) -> None:
    """Persist under the write lock. Multi-tenant forces operator-locked
    fields to None before write.
    """
    if MULTI_TENANT:
        overrides = overrides.model_copy(
            update={field: None for field in OPERATOR_LOCKED_FIELDS}
        )
    with get_session_with_current_tenant() as db_session:
        _db_upsert_overrides(db_session, overrides)
    get_kv_store().store(KV_PASSWORD_AUTH_ENABLED_KEY, overrides.password_auth_enabled)
    invalidate_security_cache(_current_tenant_id_or_default())


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


def _assert_login_path_survives(effective: SecuritySettings) -> None:
    """Refuse turning password auth off with no enabled SSO provider left."""
    if effective.password_auth_enabled:
        return
    with get_session_with_current_tenant() as db_session:
        if not fetch_sso_providers(db_session, enabled_only=True):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enable an SSO provider before turning off password login, "
                "otherwise no one can sign in.",
            )


@contextmanager
def security_settings_write_lock() -> Iterator[None]:
    """Serialize mutations that depend on the joint settings + SSO provider
    state. Raises ``OnyxError(CONFLICT)`` if a competing writer holds it past the wait
    window.
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
        yield
    finally:
        # Lease may have expired during the write. Unconditional release would
        # raise LockNotOwnedError and mask a successful save as a 500.
        if lock.owned():
            lock.release()


def load_effective_uncached() -> SecuritySettings:
    """Fresh, cache-bypassing effective settings. Use inside the write lock when
    a decision must see the latest persisted value, not a TTL-stale one."""
    return merge_with_env(_load_raw_overrides_unlocked())


def seed_jwt_settings_from_env() -> None:
    """Single-tenant api_server startup: mirror set JWT env values into the DB
    row so retiring an env var later keeps its last pinned value. While a pin is
    active the API refuses admin writes to the field, so overwriting a differing
    stored value loses nothing admin-authored. Never raises: a seed failure must
    not block boot."""
    if MULTI_TENANT:
        return
    env_values = _build_env_defaults().model_dump()
    # Nothing pinned: skip the distributed lock entirely so contention or a
    # cache-backend hiccup cannot fail a boot that has nothing to write.
    if all(env_values[name] is None for name in ENV_PINNED_FIELDS):
        return
    try:
        with security_settings_write_lock():
            existing = _load_raw_overrides_unlocked()
            existing_values = existing.model_dump()
            updates = {
                name: env_values[name]
                for name in ENV_PINNED_FIELDS
                if env_values[name] is not None
                and existing_values[name] != env_values[name]
            }
            if not updates:
                return
            _store_overrides_unlocked(existing.model_copy(update=updates))
            # System-actor audit: an overwrite of a differing stored value must
            # be as visible as an admin edit.
            _audit_settings_change(
                existing,
                existing.model_copy(update=updates),
                set(updates),
                None,
            )
            logger.notice(
                "Seeded security settings from env: %s", ", ".join(sorted(updates))
            )
    except Exception:
        logger.exception("JWT settings seed failed, continuing startup")


def env_pinned_active_fields() -> frozenset[str]:
    """Env-pinned fields whose env var is currently set, i.e. not editable."""
    env_values = _build_env_defaults().model_dump()
    return frozenset(name for name in ENV_PINNED_FIELDS if env_values[name] is not None)


def _audit_settings_change(
    existing: SecuritySettingsOverrides,
    merged: SecuritySettingsOverrides,
    present_keys: set[str],
    actor: AuditActor | None,
) -> None:
    existing_values = existing.model_dump()
    merged_values = merged.model_dump()
    changed = {
        name: {"old": existing_values[name], "new": merged_values[name]}
        for name in present_keys
        if existing_values[name] != merged_values[name]
    }
    if not changed:
        return
    emit_audit_event(
        AuditAction.SECURITY_SETTINGS_CHANGE,
        AuditOutcome.SUCCESS,
        actor=actor,
        resource_type="security_settings",
        extra={"changed": changed},
    )


def apply_patch(
    patch: SecuritySettingsOverrides,
    present_keys: set[str],
    actor: AuditActor | None = None,
) -> SecuritySettings:
    """Public write entry point. Holds the shared write lock for the full
    read-modify-write so concurrent writers can't clobber each other.

    Raises ``OnyxError(CONFLICT)`` if a competing writer holds the lock past
    the wait window, and ``OnyxError(INVALID_INPUT)`` if the merged effective
    state would violate a model invariant.
    """
    with security_settings_write_lock():
        existing = _load_raw_overrides_unlocked()
        merged = _apply_present_keys(existing, patch, present_keys)
        try:
            # SecuritySettings invariants run via model_validator on construction.
            effective = merge_with_env(merged)
        except ValidationError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))
        _assert_login_path_survives(effective)
        _store_overrides_unlocked(merged)
        _audit_settings_change(existing, merged, present_keys, actor)
        return effective


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


def get_security_settings() -> SecuritySettings:
    """Effective, env-merged, immutable settings for the current tenant.

    Pre-tenant safe: returns env defaults (uncached) when there is no real
    tenant schema to read from. DB errors fall back to env defaults so a
    Postgres outage never bricks the auth path. Returned ``SecuritySettings``
    is frozen.
    """
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    # In multi-tenant the shared/default schema carries no per-tenant
    # security_settings row, so reading it raises UndefinedTable. Unmapped users
    # (registration, login for an email with no tenant) and pre-resolution
    # requests land here; fall back to env defaults rather than a doomed query.
    if tenant_id is None or (MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA):
        return _build_env_defaults()

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


def llm_custom_config_env_injection_enabled() -> bool:
    """Whether env-only LLM provider custom_config keys may be temporarily
    injected into os.environ during a call. Hard-off on multi-tenant regardless
    of stored overrides — process-wide env vars are only safe when the admin
    owns the whole deployment."""
    if MULTI_TENANT:
        # merge_with_env forces this off on multi-tenant, so an effective True
        # here means that invariant has been broken somewhere upstream.
        if get_security_settings().llm_custom_config_env_injection:
            logger.critical(
                "Invariant violation: llm_custom_config_env_injection resolved "
                "to enabled on a multi-tenant deployment; forcing it off for "
                "this call."
            )
        return False
    return get_security_settings().llm_custom_config_env_injection
