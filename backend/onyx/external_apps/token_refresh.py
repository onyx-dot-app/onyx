"""Lazy, single-flighted OAuth token refresh for Craft external apps, called by
the egress gate.

The public entrypoint takes ids; the storage and dead-grant policy live in
:class:`_ExternalAppTokenRefresher`, while the single-flight skeleton (lock,
stale pre-check, terminal/transient/contention/infra routing) is the shared
:class:`onyx.oauth.single_flight.SingleFlightTokenRefresher`. Each step takes its
own short session, so no connection is held across the lock wait or the POST.
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.external_app import delete_external_app_user_credential
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_app_user_credential
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import get_provider_for_app
from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.expiry import needs_refresh
from onyx.oauth.expiry import stamp_expires_at
from onyx.oauth.single_flight import SingleFlightTokenRefresher
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Gathered inside a session for the POST: provider, stored creds, client id/secret.
_RefreshInputs = tuple[OAuthExternalAppProvider, dict[str, Any], str, str]


class _ExternalAppTokenRefresher(SingleFlightTokenRefresher[None]):
    """Refresh one user's stored access token for one external app.

    Storage is ``ExternalAppUserCredential``; a dead grant clears the credential
    so the app reads as disconnected. Returns ``None`` — the egress gate re-reads
    the credential after a refresh.
    """

    log_prefix = "ea_token_refresh"

    def __init__(self, tenant_id: str, external_app_id: int, user_id: UUID):
        self.tenant_id = tenant_id
        self.external_app_id = external_app_id
        self.user_id = user_id

    def lock_name(self) -> str:
        return (
            f"ea_token_refresh:{self.tenant_id}:{self.external_app_id}:{self.user_id}"
        )

    def is_stale(self) -> bool:
        # Cheap pre-check: one cred read for the staleness decision. Provider and
        # client-cred resolution happen under the lock, only when actually stale.
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            stored = _read_stored_credentials(db, self.external_app_id, self.user_id)
        return stored is not None and needs_refresh(stored, datetime.now(timezone.utc))

    def refresh_under_lock(self) -> None:
        # Re-read in a fresh session — double-check after the lock wait, in case a
        # concurrent process already refreshed — then release before the POST.
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            inputs = _load_refresh_inputs(db, self.external_app_id, self.user_id)
        if inputs is None:
            return None
        provider, stored, client_id, client_secret = inputs

        # POST with no DB connection held; raises Terminal/Transient, routed by base.
        refreshed = provider.refresh_credentials(stored, client_id, client_secret)

        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            upsert_external_app_user_credential(
                db,
                external_app_id=self.external_app_id,
                user_id=self.user_id,
                user_credentials=stamp_expires_at(
                    refreshed, datetime.now(timezone.utc)
                ),
            )
        logger.info(
            "ea_token_refresh.refreshed external_app_id=%s user_id=%s",
            self.external_app_id,
            self.user_id,
        )
        return None

    def on_terminal(self, error: TokenRefreshTerminalError) -> None:
        # Dead grant: drop the credential so the app reads as disconnected.
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            delete_external_app_user_credential(
                db, external_app_id=self.external_app_id, user_id=self.user_id
            )
        logger.warning(
            "ea_token_refresh.terminal_cleared external_app_id=%s user_id=%s error=%s",
            self.external_app_id,
            self.user_id,
            error,
        )
        return None


def ensure_fresh_credentials(
    tenant_id: str,
    external_app_id: int,
    user_id: UUID,
) -> None:
    """Refresh the user's stored access token if it's expired/expiring; a fast
    no-op otherwise. Single-flights via a Redis lock and persists the result.

    Never raises for a refresh outcome: a revoked grant clears the credential (app
    reads disconnected), and a transient / lock-contention / infra failure keeps
    the existing token so the caller proceeds with the currently-stored credential.
    """
    _ExternalAppTokenRefresher(tenant_id, external_app_id, user_id).run()


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
