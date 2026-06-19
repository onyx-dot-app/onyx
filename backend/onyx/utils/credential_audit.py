"""Structured audit logging for credential access (log-only).

Emits a single structured JSON line whenever a stored LLM-provider or connector
credential is decrypted (read in plaintext via ``get_value(apply_mask=False)``
/ a credentials provider), for observability and audit purposes. Each event
carries tenant / request / client-IP context so credential reads can be
reviewed and attributed. The secret value itself is never included.

This module is deliberately defensive: it must NEVER raise into the calling
code path (credential reads sit on the chat hot path and on connector
indexing). Every piece of context is best-effort and any failure degrades to
``None`` or to "always emit".

The emitted line goes to a dedicated logger named ``onyx.audit.credential_access``
at INFO. To consume the audit trail, filter logs on that logger name and parse
the JSON payload.
"""

import json
import logging
import time
from typing import Any

# Dedicated audit logger. We intentionally use a plain ``logging.getLogger``
# rather than ``setup_logger`` so the record message is exactly one clean JSON
# object (the Onyx standard formatter prepends a human-readable prefix, which
# would make machine parsing harder). The logger propagates to the root so it
# still reaches the configured handlers / log files.
AUDIT_LOGGER_NAME = "onyx.audit.credential_access"
_audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
_audit_logger.setLevel(logging.INFO)

# Dedup window: emit at most one event per (tenant, credential_type, row, actor)
# key within this many seconds. Keeps the chat hot path from flooding the log.
_DEDUP_TTL_SECONDS = 600


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


def _should_emit(
    tenant_id: str | None,
    credential_type: str,
    row_id: int | None,
    actor: str,
) -> bool:
    """Best-effort Redis SETNX-with-EX dedup.

    Returns True if this event should be emitted. If Redis is unavailable for
    any reason we fall back to always emitting (never raise, never silently
    drop an audit event due to infra issues).
    """
    try:
        from onyx.redis.redis_pool import get_redis_client

        client = get_redis_client(tenant_id=tenant_id)
        dedup_key = f"audit:cred_access:{tenant_id}:{credential_type}:{row_id}:{actor}"
        # set(..., nx=True) returns True only when the key did not already
        # exist; None means a prior event already claimed this window.
        result = client.set(dedup_key, "1", ex=_DEDUP_TTL_SECONDS, nx=True)
        return bool(result)
    except Exception:
        # Redis down / misconfigured / no tenant context — degrade to emit.
        return True


def emit_credential_access(
    credential_type: str,
    provider: str | None,
    row_id: int | None,
    *,
    user_id: str | None = None,
    auth_type: str | None = None,
) -> None:
    """Emit a single structured audit line for a credential decrypt event.

    Args:
        credential_type: Coarse category, e.g. "llm_provider" or "connector".
        provider: The provider / source name if known (e.g. "openai", "google_drive").
        row_id: The DB row id of the credential / LLM provider, if known.
        user_id: The acting user id, if available. May be None (e.g. at
            ``LLMProviderView.from_model`` there is no user in scope).
        auth_type: How the actor authenticated, if known.

    This function never raises. Any failure to gather context, dedup, or even
    log is swallowed so the credential read path is never disrupted.
    """
    try:
        tenant_id = _safe_get_tenant_id()
        request_id = _safe_get_request_id()
        endpoint = _safe_get_endpoint()
        client_ip = _safe_get_client_ip()

        # Actor for dedup keying: prefer explicit user, then request, then IP.
        actor = user_id or request_id or client_ip or "unknown"

        if not _should_emit(tenant_id, credential_type, row_id, actor):
            return

        payload: dict[str, Any] = {
            "ts": time.time(),
            "tenant_id": tenant_id,
            "credential_type": credential_type,
            "provider": provider,
            "row_id": row_id,
            "user_id": user_id,
            "auth_type": auth_type,
            "request_id": request_id,
            "endpoint": endpoint,
            "client_ip": client_ip,
        }
        _audit_logger.info(json.dumps(payload, default=str))
    except Exception:
        # Audit must never break the caller. Last-resort swallow.
        return
