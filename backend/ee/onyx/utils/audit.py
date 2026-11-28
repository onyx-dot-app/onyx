"""Enterprise implementation of the SIEM audit-event stream (log-only).

Emits one JSON line per security-relevant action (auth, admin-config /
access-control change, credential access) on the ``onyx.audit`` logger tree.
Field names and the action taxonomy are shaped toward OCSF so the stream maps
onto OCSF event classes (Authentication / Account Change / User Access
Management / Group Management / API Activity) and drops into any SIEM. The
customer schema and export guide is
``documentation/admins/auditing/audit_logs.mdx``; update it when the schema or
the ``AuditAction`` taxonomy changes. ``AuditAction`` values are append-only.

Callers use ``onyx.utils.audit``, which resolves here when EE is loaded.
Events are written only for tenants on the Enterprise tier, and only for the
``AuditEventCategory`` values an admin turned on in the security settings.

Invariants (from the ``credential_audit`` seed): never raise into the caller
(emission sits on hot paths), never log a secret, always tenant-tag, and dedup
hot event classes via Redis (degrade to always-emit if Redis is down).
"""

import json
import logging
import sys
import threading
import time
from enum import Enum
from typing import Any

from cachetools import TTLCache

from ee.onyx.utils.audit_stats import record_event
from onyx.utils.audit import (
    DEFAULT_AUDIT_DEDUP_TTL_SECONDS,
    AuditAction,
    AuditActor,
    AuditEventCategory,
    AuditOutcome,
)

AUDIT_SCHEMA_VERSION = "1.1"

# Root of the audit logger tree; children propagate up to the dedicated stdout
# handler configured in ``_configure_audit_logging``.
AUDIT_LOGGER_ROOT = "onyx.audit"
AUDIT_HANDLER_NAME = "onyx_audit_stdout"

# Diagnostics logger for the subsystem's own failures. Deliberately NOT under
# ``onyx.audit`` so internal warnings never land in the parsed audit stream.
_internal_logger = logging.getLogger(__name__)


class OCSFEventClass(str, Enum):
    """OCSF event class carried on every event (lets consumers route by class)."""

    AUTHENTICATION = "authentication"  # OCSF class_uid 3002
    ACCOUNT_CHANGE = "account_change"  # OCSF class_uid 3001
    USER_ACCESS_MANAGEMENT = "user_access_management"  # OCSF class_uid 3005
    GROUP_MANAGEMENT = "group_management"  # OCSF class_uid 3006
    API_ACTIVITY = "api_activity"  # OCSF class_uid 6003


_OCSF_CLASS_BY_ACTION: dict[AuditAction, OCSFEventClass] = {
    AuditAction.LOGIN: OCSFEventClass.AUTHENTICATION,
    AuditAction.LOGIN_FAILURE: OCSFEventClass.AUTHENTICATION,
    AuditAction.LOGOUT: OCSFEventClass.AUTHENTICATION,
    AuditAction.REGISTER: OCSFEventClass.AUTHENTICATION,
    AuditAction.PASSWORD_FORGOT: OCSFEventClass.AUTHENTICATION,
    AuditAction.PASSWORD_RESET: OCSFEventClass.AUTHENTICATION,
    AuditAction.EMAIL_VERIFY: OCSFEventClass.AUTHENTICATION,
    AuditAction.IMPERSONATE: OCSFEventClass.AUTHENTICATION,
    AuditAction.USER_CREATE: OCSFEventClass.ACCOUNT_CHANGE,
    AuditAction.USER_DELETE: OCSFEventClass.ACCOUNT_CHANGE,
    AuditAction.USER_DEACTIVATE: OCSFEventClass.ACCOUNT_CHANGE,
    AuditAction.USER_REACTIVATE: OCSFEventClass.ACCOUNT_CHANGE,
    AuditAction.USER_ROLE_CHANGE: OCSFEventClass.USER_ACCESS_MANAGEMENT,
    AuditAction.USER_CRAFT_ACCESS_CHANGE: OCSFEventClass.USER_ACCESS_MANAGEMENT,
    AuditAction.USER_GROUP_CHANGE: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_CREATE: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_RENAME: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_DELETE: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_PERMISSION_CHANGE: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_MANAGER_CHANGE: OCSFEventClass.GROUP_MANAGEMENT,
    AuditAction.CRAFT_DEFAULT_CHANGE: OCSFEventClass.API_ACTIVITY,
    AuditAction.DEFAULT_LANGUAGE_CHANGE: OCSFEventClass.API_ACTIVITY,
    AuditAction.LLM_GATEWAY_ENABLED_CHANGE: OCSFEventClass.API_ACTIVITY,
    AuditAction.SECURITY_SETTINGS_CHANGE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CONTEXTUAL_RAG_MODEL_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CC_PAIR_ACCESS_MODE_CHANGE: OCSFEventClass.API_ACTIVITY,
    AuditAction.LLM_PROVIDER_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.LLM_PROVIDER_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.LLM_PROVIDER_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CONNECTOR_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CONNECTOR_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CONNECTOR_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CC_PAIR_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CC_PAIR_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CC_PAIR_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.API_KEY_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.API_KEY_REGENERATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.API_KEY_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.API_KEY_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_ACCESS: OCSFEventClass.API_ACTIVITY,
    # OCSF has no authorization-denial class, so a refused request maps onto the
    # request surface instead.
    AuditAction.PERMISSION_DENIED: OCSFEventClass.API_ACTIVITY,
    AuditAction.PAT_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.PAT_REVOKE: OCSFEventClass.API_ACTIVITY,
    AuditAction.PERSONA_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.PERSONA_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.PERSONA_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.DOCUMENT_SET_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.DOCUMENT_SET_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.DOCUMENT_SET_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.EXPORT_QUERY_HISTORY: OCSFEventClass.API_ACTIVITY,
    AuditAction.EXPORT_USAGE_REPORT: OCSFEventClass.API_ACTIVITY,
    AuditAction.EXPORT_LOGS: OCSFEventClass.API_ACTIVITY,
    AuditAction.OAUTH_CLIENT_REGISTER: OCSFEventClass.API_ACTIVITY,
    AuditAction.OAUTH_GRANT_CREATE: OCSFEventClass.USER_ACCESS_MANAGEMENT,
    AuditAction.OAUTH_GRANT_REVOKE: OCSFEventClass.USER_ACCESS_MANAGEMENT,
    AuditAction.CHAT_MESSAGE_SEND: OCSFEventClass.API_ACTIVITY,
    AuditAction.SEARCH_QUERY: OCSFEventClass.API_ACTIVITY,
    AuditAction.GATEWAY_LLM_REQUEST: OCSFEventClass.API_ACTIVITY,
    AuditAction.FILE_DOWNLOAD: OCSFEventClass.API_ACTIVITY,
}

# Guard: every action must map to a class, so a new action can't ship untagged.
_unmapped = set(AuditAction) - set(_OCSF_CLASS_BY_ACTION)
if _unmapped:
    raise RuntimeError(
        f"AuditAction members missing an OCSF class mapping: "
        f"{sorted(a.value for a in _unmapped)}"
    )


_C = AuditEventCategory
_CATEGORY_BY_ACTION: dict[AuditAction, AuditEventCategory] = {
    AuditAction.LOGIN: _C.AUTHENTICATION,
    AuditAction.LOGIN_FAILURE: _C.AUTHENTICATION,
    AuditAction.LOGOUT: _C.AUTHENTICATION,
    AuditAction.REGISTER: _C.AUTHENTICATION,
    AuditAction.PASSWORD_FORGOT: _C.AUTHENTICATION,
    AuditAction.PASSWORD_RESET: _C.AUTHENTICATION,
    AuditAction.EMAIL_VERIFY: _C.AUTHENTICATION,
    AuditAction.IMPERSONATE: _C.AUTHENTICATION,
    AuditAction.USER_CREATE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_DELETE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_DEACTIVATE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_REACTIVATE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_ROLE_CHANGE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_CRAFT_ACCESS_CHANGE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_CHANGE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_CREATE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_RENAME: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_DELETE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_PERMISSION_CHANGE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.USER_GROUP_MANAGER_CHANGE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.OAUTH_GRANT_CREATE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.OAUTH_GRANT_REVOKE: _C.USER_AND_GROUP_MANAGEMENT,
    AuditAction.CRAFT_DEFAULT_CHANGE: _C.CONFIGURATION,
    AuditAction.DEFAULT_LANGUAGE_CHANGE: _C.CONFIGURATION,
    AuditAction.LLM_GATEWAY_ENABLED_CHANGE: _C.CONFIGURATION,
    AuditAction.SECURITY_SETTINGS_CHANGE: _C.CONFIGURATION,
    AuditAction.CONTEXTUAL_RAG_MODEL_UPDATE: _C.CONFIGURATION,
    AuditAction.CC_PAIR_ACCESS_MODE_CHANGE: _C.CONFIGURATION,
    AuditAction.LLM_PROVIDER_CREATE: _C.CONFIGURATION,
    AuditAction.LLM_PROVIDER_UPDATE: _C.CONFIGURATION,
    AuditAction.LLM_PROVIDER_DELETE: _C.CONFIGURATION,
    AuditAction.CONNECTOR_CREATE: _C.CONFIGURATION,
    AuditAction.CONNECTOR_UPDATE: _C.CONFIGURATION,
    AuditAction.CONNECTOR_DELETE: _C.CONFIGURATION,
    AuditAction.CC_PAIR_CREATE: _C.CONFIGURATION,
    AuditAction.CC_PAIR_UPDATE: _C.CONFIGURATION,
    AuditAction.CC_PAIR_DELETE: _C.CONFIGURATION,
    AuditAction.API_KEY_CREATE: _C.CONFIGURATION,
    AuditAction.API_KEY_REGENERATE: _C.CONFIGURATION,
    AuditAction.API_KEY_UPDATE: _C.CONFIGURATION,
    AuditAction.API_KEY_DELETE: _C.CONFIGURATION,
    AuditAction.CREDENTIAL_CREATE: _C.CONFIGURATION,
    AuditAction.CREDENTIAL_UPDATE: _C.CONFIGURATION,
    AuditAction.CREDENTIAL_DELETE: _C.CONFIGURATION,
    AuditAction.PERMISSION_DENIED: _C.CONFIGURATION,
    AuditAction.PAT_CREATE: _C.CONFIGURATION,
    AuditAction.PAT_REVOKE: _C.CONFIGURATION,
    AuditAction.PERSONA_CREATE: _C.CONFIGURATION,
    AuditAction.PERSONA_UPDATE: _C.CONFIGURATION,
    AuditAction.PERSONA_DELETE: _C.CONFIGURATION,
    AuditAction.DOCUMENT_SET_CREATE: _C.CONFIGURATION,
    AuditAction.DOCUMENT_SET_UPDATE: _C.CONFIGURATION,
    AuditAction.DOCUMENT_SET_DELETE: _C.CONFIGURATION,
    AuditAction.OAUTH_CLIENT_REGISTER: _C.CONFIGURATION,
    AuditAction.CREDENTIAL_ACCESS: _C.CREDENTIAL_ACCESS,
    AuditAction.EXPORT_QUERY_HISTORY: _C.DATA_EXPORT,
    AuditAction.EXPORT_USAGE_REPORT: _C.DATA_EXPORT,
    AuditAction.EXPORT_LOGS: _C.DATA_EXPORT,
    AuditAction.CHAT_MESSAGE_SEND: _C.CHAT,
    AuditAction.SEARCH_QUERY: _C.SEARCH,
    AuditAction.GATEWAY_LLM_REQUEST: _C.LLM_GATEWAY,
    AuditAction.FILE_DOWNLOAD: _C.FILE_DOWNLOAD,
}

_uncategorized = set(AuditAction) - set(_CATEGORY_BY_ACTION)
if _uncategorized:
    raise RuntimeError(
        f"AuditAction members missing a category: "
        f"{sorted(a.value for a in _uncategorized)}"
    )

# Written whatever the categories say, so turning a category off is itself on
# the record.
_ALWAYS_EMITTED: frozenset[AuditAction] = frozenset(
    {AuditAction.SECURITY_SETTINGS_CHANGE}
)


def category_enabled(category: AuditEventCategory) -> bool:
    """Whether the admin turned this category on. When the settings cannot be
    read, ``get_security_settings`` falls back to the defaults, so the audit
    categories stay on and user activity stays off; an unexpected error emits."""
    try:
        from onyx.server.security.store import get_security_settings

        return category in get_security_settings().audit_event_categories
    except Exception:
        _internal_logger.warning("Audit category lookup failed", exc_info=True)
        return True


def _query_text_if_allowed(query_text: str | None) -> str | None:
    """The query text, when the admin added it to events and query history
    records content in full. Fails closed: user text is the sensitive part."""
    if query_text is None:
        return None
    try:
        from onyx.configs.constants import QueryHistoryType
        from onyx.server.security.store import get_security_settings
        from onyx.server.settings.store import load_settings

        if not get_security_settings().audit_include_query_text:
            return None
        history_type = (
            load_settings(raise_on_error=True).query_history_type
            or QueryHistoryType.NORMAL
        )
        return query_text if history_type == QueryHistoryType.NORMAL else None
    except Exception:
        _internal_logger.warning("Audit query text lookup failed", exc_info=True)
        return None


# Best-effort context gathering: each degrades to ``None`` rather than raising,
# so emission works off the request path (e.g. a connector thread) too.


def _safe_get_tenant_id() -> str | None:
    try:
        from shared_configs.contextvars import get_current_tenant_id

        return get_current_tenant_id()
    except Exception:
        return None


def _safe_get_request_id() -> str | None:
    try:
        from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

        return ONYX_REQUEST_ID_CONTEXTVAR.get()
    except Exception:
        return None


def _safe_get_endpoint() -> str | None:
    try:
        from shared_configs.contextvars import CURRENT_ENDPOINT_CONTEXTVAR

        return CURRENT_ENDPOINT_CONTEXTVAR.get()
    except Exception:
        return None


def _safe_get_client_ip() -> str | None:
    try:
        from onyx.utils.client_ip import current_client_ip

        return current_client_ip()
    except Exception:
        return None


# Emission is checked on hot paths, and ``get_tier`` reads the cache backend on
# every call, so each process keeps the answer per tenant for a short time.
_TIER_CACHE_TTL_SECONDS = 60.0
_tier_cache: TTLCache[str, bool] = TTLCache(
    maxsize=10_000, ttl=_TIER_CACHE_TTL_SECONDS, timer=time.monotonic
)
_tier_cache_lock = threading.Lock()


def audit_enabled_for_tenant(tenant_id: str | None) -> bool:
    """``True`` when the tenant's license tier includes the audit stream
    (Enterprise). An exception from the tier lookup emits (fails open), and
    that answer is cached too, so a process that cannot resolve the tier warns
    once per window, not once per event. ``get_tier`` handles its own cache
    errors with a fallback tier (Business on multi-tenant), which this uses
    as given."""
    key = tenant_id or ""
    with _tier_cache_lock:
        cached = _tier_cache.get(key)
    if cached is not None:
        return cached
    try:
        from ee.onyx.utils.tier import get_tier
        from onyx.server.settings.models import Tier
        from onyx.server.settings.tier_order import tier_at_least

        enabled = tier_at_least(get_tier(tenant_id), Tier.ENTERPRISE)
    except Exception:
        _internal_logger.warning(
            "Audit tier lookup failed; emitting events for this tenant",
            exc_info=True,
        )
        enabled = True
    with _tier_cache_lock:
        _tier_cache[key] = enabled
    return enabled


def should_emit(dedup_key: str, ttl_seconds: int, tenant_id: str | None) -> bool:
    """Set-if-absent dedup with a TTL. ``True`` if the window wasn't already
    claimed; degrades to always-emit (``True``) if the cache is unavailable."""
    try:
        from onyx.cache.factory import get_cache_backend

        cache = get_cache_backend(tenant_id=tenant_id)
        return cache.set_if_absent(f"audit:{dedup_key}", "1", ex=ttl_seconds)
    except Exception:
        return True


def emit_audit_event(
    action: AuditAction,
    outcome: AuditOutcome,
    *,
    actor: AuditActor | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    dedup_key: str | None = None,
    dedup_ttl_seconds: int = DEFAULT_AUDIT_DEDUP_TTL_SECONDS,
    extra: dict[str, Any] | None = None,
    query_text: str | None = None,
) -> None:
    """Emit one structured audit line. Never raises.

    Tenant / request / endpoint / client-IP context is gathered automatically.
    Pass ``dedup_key`` for high-volume actions to suppress duplicates within
    ``dedup_ttl_seconds`` (omit it for low-volume config/access changes). Never
    put secrets in ``extra``.
    """
    try:
        tenant_id = _safe_get_tenant_id()

        # Check the tier and category before the dedup, so a dropped event
        # claims no window.
        if not audit_enabled_for_tenant(tenant_id):
            return
        if action not in _ALWAYS_EMITTED and not category_enabled(
            _CATEGORY_BY_ACTION[action]
        ):
            return

        if dedup_key is not None and not should_emit(
            dedup_key, dedup_ttl_seconds, tenant_id
        ):
            return

        ocsf_class = _OCSF_CLASS_BY_ACTION.get(action)

        payload: dict[str, Any] = {
            "audit_schema_version": AUDIT_SCHEMA_VERSION,
            "ts": time.time(),
            "action": action.value,
            "ocsf_class": ocsf_class.value if ocsf_class else None,
            "outcome": outcome.value,
            "tenant_id": tenant_id,
            "actor": actor.to_dict() if actor else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "request_id": _safe_get_request_id(),
            "endpoint": _safe_get_endpoint(),
            "source_ip": _safe_get_client_ip(),
            "extra": extra or None,
        }
        allowed_query_text = _query_text_if_allowed(query_text)
        if allowed_query_text is not None:
            payload["extra"] = {**(extra or {}), "query_text": allowed_query_text}

        # JSON as the message body so it parses identically under plain/json
        # LOG_FORMAT; default=str keeps a stray value from raising.
        _logger_for(ocsf_class).info(json.dumps(payload, default=str))
        record_event(tenant_id, ocsf_class.value if ocsf_class else "unclassified")
    except Exception:
        # Audit must never break the caller.
        return


def _configure_audit_logging() -> None:
    """Own an INFO stdout handler on ``onyx.audit`` so events reach stdout
    regardless of host-process logging. Relying on root propagation dropped
    every event under uvicorn (root unconfigured -> WARNING ``lastResort``).
    ``propagate=False`` keeps output identical across processes and avoids
    double-logging where root is configured (celery). Idempotent.
    """
    audit_root = logging.getLogger(AUDIT_LOGGER_ROOT)
    if any(h.name == AUDIT_HANDLER_NAME for h in audit_root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.name = AUDIT_HANDLER_NAME
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_root.addHandler(handler)
    audit_root.setLevel(logging.INFO)
    audit_root.propagate = False


# IMPORT-TIME SIDE EFFECT (deliberate): configure the audit handler on import
# so the subsystem is self-contained in every process that imports it. A
# startup-hook entrypoint would reintroduce the bug this fixes -- a process
# emitting events without having called it drops them silently. Idempotent and
# inert until an event is actually emitted.
_configure_audit_logging()


def _logger_for(ocsf_class: OCSFEventClass | None) -> logging.Logger:
    name = (
        AUDIT_LOGGER_ROOT
        if ocsf_class is None
        else f"{AUDIT_LOGGER_ROOT}.{ocsf_class.value}"
    )
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger
