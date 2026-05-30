"""Lazy, single-flighted OAuth token refresh, called by the egress gate.

The caller passes a tenant-scoped session *factory* (not a session) and ids;
everything else — staleness, the Redis lock, the token POST, persistence — lives
behind :func:`ensure_fresh_credentials`. Each step takes its own short session, so
no connection is held across the lock wait or the POST.
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.external_app import delete_external_app_user_credential
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_app_user_credential
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import TokenRefreshTerminalError
from onyx.external_apps.providers.base import TokenRefreshTransientError
from onyx.external_apps.providers.registry import get_provider_for_app
from onyx.external_apps.token_utils import needs_refresh
from onyx.external_apps.token_utils import stamp_expires_at
from onyx.redis.lock_context import redis_shared_lock
from onyx.redis.lock_context import RedisSharedLockAcquisitionError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Held long enough for the POST + DB steps; short wait so a waiter doesn't hold a
# worker thread for long (a timed-out waiter proceeds while the winner refreshes).
_LOCK_HELD_S = 30.0
_LOCK_WAIT_S = 5.0

# Gathered inside a session for the POST: provider, stored creds, client id/secret.
_RefreshInputs = tuple[OAuthExternalAppProvider, dict[str, Any], str, str]


def ensure_fresh_credentials(
    tenant_id: str,
    external_app_id: int,
    user_id: UUID,
) -> None:
    """Refresh the user's stored access token if it's expired/expiring; a fast
    no-op otherwise. Opens its own short sessions, single-flights via a Redis
    lock, and persists the result.

    Never raises for a refresh outcome: a revoked grant clears the credential
    (app reads disconnected), a transient failure keeps the existing token, and
    lock contention yields to the concurrent refresher.
    """
    lock_name = f"ea_token_refresh:{tenant_id}:{external_app_id}:{user_id}"
    try:
        # Cheap pre-check: just the staleness decision (one cred read), no provider
        # or client-cred resolution — those happen under the lock, only when stale.
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            stored = _read_stored_credentials(db, external_app_id, user_id)
        if stored is None or not needs_refresh(stored, datetime.now(timezone.utc)):
            return

        with redis_shared_lock(
            lock_name,
            max_time_lock_held_s=_LOCK_HELD_S,
            wait_for_lock_s=_LOCK_WAIT_S,
            logger=logger,
        ):
            _refresh_under_lock(tenant_id, external_app_id, user_id)
    except RedisSharedLockAcquisitionError:
        # Lock winner is refreshing; proceed with the current token.
        logger.info(
            "ea_token_refresh.lock_contended external_app_id=%s user_id=%s",
            external_app_id,
            user_id,
        )
    except (RedisError, SQLAlchemyError) as exc:
        # Transient infra failure — Keep existing tokens and let requests through
        logger.warning(
            "ea_token_refresh.infra_unavailable external_app_id=%s user_id=%s error=%s",
            external_app_id,
            user_id,
            exc,
        )


def _refresh_under_lock(
    tenant_id: str,
    external_app_id: int,
    user_id: UUID,
) -> None:
    # Re-read in a fresh session — double-check after the lock wait, in case a
    # concurrent process already refreshed — then release before the POST.
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        inputs = _load_refresh_inputs(db, external_app_id, user_id)
    if inputs is None:
        return
    provider, stored, client_id, client_secret = inputs

    # POST with no DB connection held.
    try:
        refreshed = provider.refresh_credentials(stored, client_id, client_secret)
    except TokenRefreshTransientError as exc:
        # Keep the existing token; retry on a later request.
        logger.warning(
            "ea_token_refresh.transient external_app_id=%s error=%s",
            external_app_id,
            exc,
        )
        return
    except TokenRefreshTerminalError as exc:
        # Dead grant: drop the credential so the app reads as disconnected.
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            delete_external_app_user_credential(
                db, external_app_id=external_app_id, user_id=user_id
            )
        logger.warning(
            "ea_token_refresh.terminal_cleared external_app_id=%s user_id=%s error=%s",
            external_app_id,
            user_id,
            exc,
        )
        return

    with get_session_with_tenant(tenant_id=tenant_id) as db:
        upsert_external_app_user_credential(
            db,
            external_app_id=external_app_id,
            user_id=user_id,
            user_credentials=stamp_expires_at(refreshed, datetime.now(timezone.utc)),
        )
    logger.info(
        "ea_token_refresh.refreshed external_app_id=%s user_id=%s",
        external_app_id,
        user_id,
    )


def _load_refresh_inputs(
    db: Session, external_app_id: int, user_id: UUID
) -> _RefreshInputs | None:
    """The POST inputs, or ``None`` when there's nothing to do (app gone /
    non-OAuth / no stored creds / token still fresh / no client creds)."""
    app = get_external_app_by_id(db, external_app_id)
    if app is None:
        return None
    provider = get_provider_for_app(app)
    if not isinstance(provider, OAuthExternalAppProvider):
        return None

    stored = _read_stored_credentials(db, external_app_id, user_id)
    if stored is None or not needs_refresh(stored, datetime.now(timezone.utc)):
        return None

    client = _client_credentials(app)
    if client is None:
        logger.warning(
            "ea_token_refresh.missing_client_creds external_app_id=%s", external_app_id
        )
        return None
    client_id, client_secret = client
    return provider, stored, client_id, client_secret


def _read_stored_credentials(
    db: Session, external_app_id: int, user_id: UUID
) -> dict[str, Any] | None:
    """The user's stored credential dict for an app, or None if unset."""
    user_cred = get_external_app_user_credential(
        db, external_app_id=external_app_id, user_id=user_id
    )
    if user_cred is None:
        return None
    return user_cred.user_credentials.get_value(apply_mask=False)


def _client_credentials(app: ExternalApp) -> tuple[str, str] | None:
    """The app's OAuth client_id/client_secret, or None if an admin hasn't set them."""
    org_credentials = app.organization_credentials.get_value(apply_mask=False)
    client_id = org_credentials.get("client_id")
    client_secret = org_credentials.get("client_secret")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret
