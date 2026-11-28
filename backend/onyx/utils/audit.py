"""Call-site surface of the SIEM audit-event stream.

Call sites name actions and actors with the types here. Emission is an
Enterprise feature: ``emit_audit_event`` resolves to ``ee.onyx.utils.audit``
when EE is loaded and does nothing otherwise. See that module for the schema
and the invariants. ``AuditAction`` values are append-only.
"""

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, SkipValidation

from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

# Diagnostics logger for the subsystem's own failures. Deliberately NOT under
# ``onyx.audit`` so internal warnings never land in the parsed audit stream.
_internal_logger = logging.getLogger(__name__)

DEFAULT_AUDIT_DEDUP_TTL_SECONDS = 600


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

    # User access management
    USER_ROLE_CHANGE = "user.role_change"
    USER_CRAFT_ACCESS_CHANGE = "user.craft_access_change"

    # Group management
    USER_GROUP_CHANGE = "user.group_change"
    USER_GROUP_CREATE = "user_group.create"
    USER_GROUP_RENAME = "user_group.rename"
    USER_GROUP_DELETE = "user_group.delete"
    USER_GROUP_PERMISSION_CHANGE = "user_group.permission_change"
    USER_GROUP_MANAGER_CHANGE = "user_group.manager_change"

    # API activity (admin config + resource CRUD)
    CRAFT_DEFAULT_CHANGE = "settings.craft_default_change"
    DEFAULT_LANGUAGE_CHANGE = "settings.default_language_change"
    LLM_GATEWAY_ENABLED_CHANGE = "settings.llm_gateway_enabled_change"
    SECURITY_SETTINGS_CHANGE = "settings.security_settings_change"
    CONTEXTUAL_RAG_MODEL_UPDATE = "search_settings.contextual_rag_model_update"
    CC_PAIR_ACCESS_MODE_CHANGE = "search_settings.cc_pair_access_mode_change"
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
    API_KEY_UPDATE = "api_key.update"
    API_KEY_DELETE = "api_key.delete"
    CREDENTIAL_CREATE = "credential.create"
    CREDENTIAL_UPDATE = "credential.update"
    CREDENTIAL_DELETE = "credential.delete"
    CREDENTIAL_ACCESS = "credential.access"
    # Fires only when a scoped write gate refuses an actor who already holds
    # partial authority, not on every 403.
    PERMISSION_DENIED = "permission.denied"
    PAT_CREATE = "pat.create"
    PAT_REVOKE = "pat.revoke"
    PERSONA_CREATE = "persona.create"
    PERSONA_UPDATE = "persona.update"
    PERSONA_DELETE = "persona.delete"
    DOCUMENT_SET_CREATE = "document_set.create"
    DOCUMENT_SET_UPDATE = "document_set.update"
    DOCUMENT_SET_DELETE = "document_set.delete"
    # Exports fire when the file is downloaded, which is when data leaves Onyx.
    EXPORT_QUERY_HISTORY = "export.query_history"
    EXPORT_USAGE_REPORT = "export.usage_report"
    EXPORT_LOGS = "export.logs"
    OAUTH_CLIENT_REGISTER = "oauth_client.register"
    OAUTH_GRANT_CREATE = "oauth_grant.create"
    OAUTH_GRANT_REVOKE = "oauth_grant.revoke"


class AuditActor(BaseModel):
    """Who performed the action; all fields optional. Never a secret —
    ``api_key_id`` is the key's id, never its value."""

    model_config = ConfigDict(strict=True, frozen=True)

    user_id: str | None = None
    email: SkipValidation[str | None] = None
    api_key_id: str | None = None
    auth_type: str | None = None  # e.g. "password", "oauth", "saml", "api_key"
    # The credential that authenticated the request: a ``UsageCredentialType``
    # value and that credential's id (PAT id, API key id, OAuth grant id).
    # Filled from the request context when the actor is the requester.
    credential_type: str | None = None
    credential_id: str | None = None
    oauth_client_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "api_key_id": self.api_key_id,
            "auth_type": self.auth_type,
            "credential_type": self.credential_type,
            "credential_id": self.credential_id,
            "oauth_client_id": self.oauth_client_id,
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
            email=getattr(user, "email", None),  # ods: ignore[getattr]
            auth_type=auth_type,
        )
    except Exception:
        # Don't raise into the caller, but surface the failure for diagnosis
        # (distinguishes an internal error from a genuinely absent user).
        _internal_logger.warning("actor_from_user failed to build actor", exc_info=True)
        return None


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
) -> None:
    """Emit one structured audit line when EE is loaded. Never raises.

    Pass ``dedup_key`` for high-volume actions to suppress duplicates within
    ``dedup_ttl_seconds`` (omit it for low-volume config/access changes). Never
    put secrets in ``extra``.
    """
    try:
        emit = fetch_ee_implementation_or_noop("onyx.utils.audit", "emit_audit_event")
    except Exception:
        # Audit must never break the caller.
        _internal_logger.warning("Failed to load the audit emitter", exc_info=True)
        return
    # A missing EE module resolves to this CE function; calling it would recurse.
    if emit is emit_audit_event:
        return
    emit(
        action,
        outcome,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        dedup_key=dedup_key,
        dedup_ttl_seconds=dedup_ttl_seconds,
        extra=extra,
    )
