"""Structured, SIEM-exportable audit-event subsystem (log-only).

Emits one JSON line per security-relevant action (auth, admin-config /
access-control change, credential access) on the ``onyx.audit`` logger tree.
Field names and the action taxonomy are shaped toward OCSF so the stream maps
onto OCSF event classes (Authentication / Account Change / API Activity) and
drops into any SIEM. See ``docs/AUDIT_LOGGING.md`` for the schema + export path.

Invariants (from the ``credential_audit`` seed): never raise into the caller
(emission sits on hot paths), never log a secret, always tenant-tag, and dedup
hot event classes via Redis (degrade to always-emit if Redis is down).
"""

import json
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

AUDIT_SCHEMA_VERSION = "1.0"

# Root of the audit logger tree; children propagate up to the dedicated stdout
# handler configured in ``_configure_audit_logging``.
AUDIT_LOGGER_ROOT = "onyx.audit"
AUDIT_HANDLER_NAME = "onyx_audit_stdout"

# Diagnostics logger for the subsystem's own failures. Deliberately NOT under
# ``onyx.audit`` so internal warnings never land in the parsed audit stream.
_internal_logger = logging.getLogger(__name__)

_DEFAULT_DEDUP_TTL_SECONDS = 600


class OCSFEventClass(str, Enum):
    """OCSF event class carried on every event (lets consumers route by class)."""

    AUTHENTICATION = "authentication"  # OCSF class_uid 3002
    ACCOUNT_CHANGE = "account_change"  # OCSF class_uid 3001
    API_ACTIVITY = "api_activity"  # OCSF class_uid 6003


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"  # authn/authz refusal, distinct from an operational error


class AuditAction(str, Enum):
    """Audited-action taxonomy. Values are an append-only schema contract
    (consumers filter on them)."""

    # Authentication
    LOGIN = "auth.login"
    LOGIN_FAILURE = "auth.login_failure"
    LOGOUT = "auth.logout"
    REGISTER = "auth.register"
    PASSWORD_FORGOT = "auth.password_forgot"
    PASSWORD_RESET = "auth.password_reset"
    EMAIL_VERIFY = "auth.email_verify"
    IMPERSONATE = "auth.impersonate"  # cloud superuser assuming another user's session

    # Account change
    USER_CREATE = "user.create"
    USER_DELETE = "user.delete"
    USER_DEACTIVATE = "user.deactivate"
    USER_REACTIVATE = "user.reactivate"
    USER_ROLE_CHANGE = "user.role_change"
    USER_GROUP_CHANGE = "user.group_change"

    # API activity (admin config + resource CRUD)
    LLM_PROVIDER_CREATE = "llm_provider.create"
    LLM_PROVIDER_UPDATE = "llm_provider.update"
    LLM_PROVIDER_DELETE = "llm_provider.delete"
    CONNECTOR_CREATE = "connector.create"
    CONNECTOR_UPDATE = "connector.update"
    CONNECTOR_DELETE = "connector.delete"
    CC_PAIR_CREATE = "cc_pair.create"
    CC_PAIR_UPDATE = "cc_pair.update"
    CC_PAIR_DELETE = "cc_pair.delete"
    API_KEY_CREATE = "api_key.create"
    API_KEY_REGENERATE = "api_key.regenerate"
    API_KEY_DELETE = "api_key.delete"
    CREDENTIAL_CREATE = "credential.create"
    CREDENTIAL_UPDATE = "credential.update"
    CREDENTIAL_DELETE = "credential.delete"
    CREDENTIAL_ACCESS = "credential.access"


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
    AuditAction.USER_ROLE_CHANGE: OCSFEventClass.ACCOUNT_CHANGE,
    AuditAction.USER_GROUP_CHANGE: OCSFEventClass.ACCOUNT_CHANGE,
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
    AuditAction.API_KEY_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_CREATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_UPDATE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_DELETE: OCSFEventClass.API_ACTIVITY,
    AuditAction.CREDENTIAL_ACCESS: OCSFEventClass.API_ACTIVITY,
}

# Guard: every action must map to a class, so a new action can't ship untagged.
_unmapped = set(AuditAction) - set(_OCSF_CLASS_BY_ACTION)
if _unmapped:
    raise RuntimeError(
        f"AuditAction members missing an OCSF class mapping: "
        f"{sorted(a.value for a in _unmapped)}"
    )


@dataclass(frozen=True)
class AuditActor:
    """Who performed the action; all fields optional. Never a secret —
    ``api_key_id`` is the key's id, never its value."""

    user_id: str | None = None
    email: str | None = None
    api_key_id: str | None = None
    auth_type: str | None = None  # e.g. "password", "oauth", "saml", "api_key"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "api_key_id": self.api_key_id,
            "auth_type": self.auth_type,
        }


def actor_from_user(
    user: Any | None, *, auth_type: str | None = None
) -> AuditActor | None:
    """Build an ``AuditActor`` from a fastapi-users ``User`` (best-effort).

    Returns ``None`` when there's no user. Typed ``Any`` so this module stays
    free of an import dependency on the ORM/User model. Never raises."""
    if user is None:
        return None
    try:
        return AuditActor(
            user_id=str(user.id),
            email=getattr(user, "email", None),
            auth_type=auth_type,
        )
    except Exception:
        # Don't raise into the caller, but surface the failure for diagnosis
        # (distinguishes an internal error from a genuinely absent user).
        _internal_logger.warning("actor_from_user failed to build actor", exc_info=True)
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


def should_emit(dedup_key: str, ttl_seconds: int, tenant_id: str | None) -> bool:
    """Redis ``SETNX``-with-``EX`` dedup. ``True`` if the window wasn't already
    claimed; degrades to always-emit (``True``) if Redis is unavailable."""
    try:
        from onyx.redis.redis_pool import get_redis_client

        client = get_redis_client(tenant_id=tenant_id)
        # nx=True returns truthy only when the key didn't exist (window is free).
        result = client.set(f"audit:{dedup_key}", "1", ex=ttl_seconds, nx=True)
        return bool(result)
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
    dedup_ttl_seconds: int = _DEFAULT_DEDUP_TTL_SECONDS,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit one structured audit line. Never raises.

    Tenant / request / endpoint / client-IP context is gathered automatically.
    Pass ``dedup_key`` for high-volume actions to suppress duplicates within
    ``dedup_ttl_seconds`` (omit it for low-volume config/access changes). Never
    put secrets in ``extra``.
    """
    try:
        tenant_id = _safe_get_tenant_id()

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

        # JSON as the message body so it parses identically under plain/json
        # LOG_FORMAT; default=str keeps a stray value from raising.
        _logger_for(ocsf_class).info(json.dumps(payload, default=str))
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
