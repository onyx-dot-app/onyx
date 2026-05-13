"""OAuth flow routes for External Apps.

Provider-agnostic: each supported provider is one entry in `PROVIDERS`
(in `external_apps.providers`) keyed on the `external_app.name`
value. The shared routes here look up the matching provider and use
its authorize URL, scope, token URL, and response-parser. Adding a
new OAuth provider = add one entry to `PROVIDERS`, no changes here.

Flow:
  1. Frontend hits `GET /apps/{id}/oauth/start` → backend stores a state
     UUID in Redis with the (user_id, external_app_id) it represents,
     returns the provider's authorize URL pointing at our frontend
     callback page.
  2. User consents on the provider, gets redirected back to the
     frontend callback page with `code` and `state` in the URL.
  3. Frontend `POST /apps/oauth/callback` with `code` and `state` →
     backend validates the state, exchanges the code for tokens at the
     provider's token endpoint, and stores them in
     `external_app_user_credential.user_credentials`.

`client_id` / `client_secret` are pulled from the matching app row's
`organization_credentials` (admin-entered via the Manage Apps UI), so
each tenant can register its own OAuth client per provider without
server env vars.
"""

import base64
import uuid
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import upsert_external_app_user_credential__no_commit
from onyx.db.models import ExternalApp
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers import get_provider_or_raise
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()

# The frontend page that receives the redirect after consent. Must be
# registered as a redirect URI in each provider's developer console.
_FRONTEND_CALLBACK_PATH = "/craft/v1/apps/oauth/callback"

# Redis key prefix for state UUIDs. Distinct from `da_oauth:` used by
# the existing Slack-connector OAuth flow so the two don't collide.
_REDIS_KEY_PREFIX = "da_ea_oauth:"
_REDIS_STATE_TTL_SECONDS = 600


def _oauth_client_credentials(app: ExternalApp) -> tuple[str, str]:
    """Pull (client_id, client_secret) from the app's organization
    credentials. All supported providers use the same key names; if a
    future provider uses different ones, branch on `app.name` here.
    """
    client_id = app.organization_credentials.get("client_id")
    client_secret = app.organization_credentials.get("client_secret")
    if not client_id or not client_secret:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{app.name} is missing client_id or client_secret — "
            "ask an admin to fill them in on the Manage Apps page.",
        )
    return client_id, client_secret


def _frontend_callback_url() -> str:
    """Where the provider redirects after consent. The frontend handles
    `code` and `state` from the query string and POSTs them back to us."""
    return f"{WEB_DOMAIN}{_FRONTEND_CALLBACK_PATH}"


def _token_response_is_error(
    http_response: requests.Response, body: dict[str, Any]
) -> str | None:
    """Detect an error response across providers with different shapes.

    - Slack: HTTP 200 with `{"ok": false, "error": "..."}` on failure.
    - Google (and most standards-compliant providers): non-2xx HTTP
      with `{"error": "...", "error_description": "..."}` body.
    Returns the error string if this is a failure, else None.
    """
    if http_response.status_code >= 400:
        return body.get("error_description") or body.get("error") or "unknown"
    if body.get("ok") is False:
        return body.get("error") or "unknown"
    return None


# ── Pydantic models ─────────────────────────────────────────────────


class OAuthStartResponse(BaseModel):
    authorize_url: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    success: bool
    external_app_id: int


class _OAuthStateRecord(BaseModel):
    """Redis-stored mapping from a state UUID to the request context."""

    user_id: str
    external_app_id: int


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/apps/{external_app_id}/oauth/start")
def start_external_app_oauth(
    external_app_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> OAuthStartResponse:
    """Begin an OAuth flow for the given external app on behalf of the
    calling user.

    Returns 404 if the app does not exist, 400 if it is disabled, isn't
    a supported OAuth-backed app, or its admin-supplied
    client_id/client_secret are missing from `organization_credentials`.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )
    if not app.enabled:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This app is currently disabled by an admin.",
        )
    provider = get_provider_or_raise(app)
    client_id, _client_secret = _oauth_client_credentials(app)

    oauth_uuid = uuid.uuid4()
    state = base64.urlsafe_b64encode(oauth_uuid.bytes).rstrip(b"=").decode("ascii")

    tenant_id = get_current_tenant_id()
    r = get_redis_client(tenant_id=tenant_id)
    record = _OAuthStateRecord(user_id=str(user.id), external_app_id=external_app_id)
    r.set(
        f"{_REDIS_KEY_PREFIX}{oauth_uuid}",
        record.model_dump_json(),
        ex=_REDIS_STATE_TTL_SECONDS,
    )

    redirect_uri = _frontend_callback_url()
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        provider.scope_param: provider.scope,
        "state": state,
        **provider.extra_authorize_params,
    }
    # `urlencode` so non-trivial scope values (e.g. Google's URI-shaped
    # scopes like `https://www.googleapis.com/auth/calendar`) get
    # encoded — raw f-strings would leave `:` and `/` unescaped.
    authorize_url = f"{provider.authorize_url}?{urlencode(params)}"
    return OAuthStartResponse(authorize_url=authorize_url)


@router.post("/apps/oauth/callback")
def handle_external_app_oauth_callback(
    request: OAuthCallbackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> OAuthCallbackResponse:
    """Exchange an OAuth `code` for tokens and persist them as the
    calling user's credentials for the external app encoded in `state`.

    Validates that the state was issued for *this* user — a stolen
    state UUID can't be redeemed by a different account.
    """
    tenant_id = get_current_tenant_id()
    r = get_redis_client(tenant_id=tenant_id)

    # Recover the UUID from urlsafe-b64 (state arrives without padding).
    padded_state = request.state + "=" * (-len(request.state) % 4)
    try:
        uuid_bytes = base64.urlsafe_b64decode(padded_state)
        oauth_uuid = uuid.UUID(bytes=uuid_bytes)
    except (ValueError, TypeError):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Malformed OAuth state.")

    redis_key = f"{_REDIS_KEY_PREFIX}{oauth_uuid}"
    record_bytes = r.get(redis_key)
    if record_bytes is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth state expired or unknown — restart the connection flow.",
        )
    record = _OAuthStateRecord.model_validate_json(record_bytes.decode("utf-8"))

    # Bind the state to the user it was issued for: prevents one user's
    # in-flight OAuth state from being redeemed by another user.
    if record.user_id != str(user.id):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "OAuth state does not match the calling user.",
        )

    app = get_external_app_by_id(db_session, record.external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {record.external_app_id} no longer exists.",
        )

    provider = get_provider_or_raise(app)
    # Re-read client_id/client_secret from the app row. If an admin
    # rotated creds between /oauth/start and the callback, we honor the
    # latest values — anything else would silently use stale creds.
    client_id, client_secret = _oauth_client_credentials(app)

    # `grant_type=authorization_code` is required by Google (and the
    # OAuth 2.0 spec); Slack permits omitting it but accepts it, so we
    # always send it.
    response = requests.post(
        provider.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": request.code,
            "redirect_uri": _frontend_callback_url(),
        },
        timeout=30,
    )
    response_data = response.json()

    error = _token_response_is_error(response, response_data)
    if error:
        logger.warning(
            "%s OAuth token exchange failed for user %s, app %d: %s",
            app.name,
            user.id,
            app.id,
            error,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.name} OAuth failed: {error}",
        )

    stored_credentials = provider.extract_credentials(response_data)

    upsert_external_app_user_credential__no_commit(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=stored_credentials,
    )
    db_session.commit()

    # One-shot state — delete after a successful redemption so a stolen
    # callback URL can't be replayed.
    r.delete(redis_key)

    return OAuthCallbackResponse(success=True, external_app_id=app.id)
