import secrets
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.external_app import (
    get_external_app_by_id,
    upsert_external_app_user_credential,
)
from onyx.db.models import ExternalApp, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider, OAuthFlowSpec
from onyx.external_apps.providers.registry import get_provider_or_raise
from onyx.external_apps.token_utils import stamp_expires_at
from onyx.oauth.authorization_attempt import (
    AuthorizationAttemptStore,
    canonical_json_fingerprint,
    generate_authorization_state,
)
from onyx.oauth.models import (
    OAuthConfigurationFingerprint,
    PKCECodeVerifier,
    SafeOAuthReturnPath,
)
from onyx.oauth.protocol import build_authorization_url
from onyx.server.features.build.external_apps.models import (
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthStartResponse,
)
from onyx.skills.push import push_skills_for_users
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter()

# Must be registered as a redirect URI in each provider's developer
# console.
_FRONTEND_CALLBACK_URL = f"{WEB_DOMAIN}/craft/v1/apps/oauth/callback"


class _ExternalAppOAuthAttemptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_app_id: int
    configuration_fingerprint: OAuthConfigurationFingerprint
    code_verifier: PKCECodeVerifier | None = None
    return_path: SafeOAuthReturnPath | None = None


_AUTHORIZATION_ATTEMPTS = AuthorizationAttemptStore(
    cache_backend_provider=get_cache_backend,
    namespace="external-app",
    payload_type=_ExternalAppOAuthAttemptPayload,
)


def _oauth_client_credentials(app: ExternalApp) -> tuple[str, str]:
    org_credentials = app.organization_credentials.get_value(apply_mask=False)
    client_id = org_credentials.get("client_id")
    client_secret = org_credentials.get("client_secret")
    if not client_id or not client_secret:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{app.name} is missing client_id or client_secret — "
            "ask an admin to fill them in on the Manage Apps page.",
        )
    return client_id, client_secret


def _oauth_provider_or_raise(app: ExternalApp) -> OAuthExternalAppProvider:
    """Resolve the app's provider and assert it authenticates via OAuth, or
    400. Only the OAuth subset of built-in providers can drive these routes."""
    provider = get_provider_or_raise(app)
    if not isinstance(provider, OAuthExternalAppProvider):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"App '{app.name}' does not use an OAuth flow.",
        )
    return provider


def _configuration_fingerprint(
    app: ExternalApp,
    oauth: OAuthFlowSpec,
    client_id: str,
    client_secret: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "app_type": app.app_type.value,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _FRONTEND_CALLBACK_URL,
            "oauth": oauth.model_dump(mode="json"),
        },
    )


@router.get("/apps/{external_app_id}/oauth/start")
def start_external_app_oauth(
    external_app_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
    return_path: str | None = None,
) -> OAuthStartResponse:
    try:
        return_path = TypeAdapter(SafeOAuthReturnPath | None).validate_python(
            return_path
        )
    except ValueError:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "return_path must be a safe internal path"
        )
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
    provider = _oauth_provider_or_raise(app)
    client_id, client_secret = _oauth_client_credentials(app)
    oauth = provider.resolve_oauth_flow(
        app.organization_credentials.get_value(apply_mask=False)
    )

    additional_params = dict(oauth.extra_authorize_params)
    if oauth.optional_scope:
        additional_params[oauth.optional_scope_param] = oauth.optional_scope

    code_verifier: str | None = None
    code_challenge: str | None = None
    if oauth.supports_pkce:
        code_verifier, code_challenge = generate_pkce_pair()

    state = generate_authorization_state()
    authorize_url = build_authorization_url(
        authorization_url=oauth.authorize_url,
        client_id=client_id,
        redirect_uri=_FRONTEND_CALLBACK_URL,
        state=state,
        scope=oauth.scope,
        scope_param=oauth.scope_param,
        additional_params=additional_params,
        code_challenge=code_challenge,
    )
    _AUTHORIZATION_ATTEMPTS.store(
        owner_id=str(user.id),
        state=state,
        payload=_ExternalAppOAuthAttemptPayload(
            external_app_id=external_app_id,
            configuration_fingerprint=_configuration_fingerprint(
                app, oauth, client_id, client_secret
            ),
            code_verifier=code_verifier,
            return_path=return_path,
        ),
    )
    return OAuthStartResponse(authorize_url=authorize_url)


@router.post("/apps/oauth/callback")
def handle_external_app_oauth_callback(
    request: OAuthCallbackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> OAuthCallbackResponse:
    attempt = _AUTHORIZATION_ATTEMPTS.consume(
        owner_id=str(user.id), state=request.state
    )
    payload = attempt.payload

    app = get_external_app_by_id(db_session, payload.external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {payload.external_app_id} no longer exists.",
        )
    if not app.enabled:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This app is currently disabled by an admin.",
        )

    provider = _oauth_provider_or_raise(app)
    # Re-read in case the admin rotated creds between /start and /callback.
    client_id, client_secret = _oauth_client_credentials(app)
    oauth = provider.resolve_oauth_flow(
        app.organization_credentials.get_value(apply_mask=False)
    )
    if not secrets.compare_digest(
        payload.configuration_fingerprint,
        _configuration_fingerprint(app, oauth, client_id, client_secret),
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "External app OAuth configuration changed while authorization was pending.",
        )

    token_request = provider.build_token_exchange_request(
        request.code,
        client_id,
        client_secret,
        _FRONTEND_CALLBACK_URL,
        code_verifier=payload.code_verifier,
    )
    try:
        response = requests.post(
            oauth.token_url,
            headers=token_request.headers,
            data=None if token_request.json_encoded else token_request.body,
            json=token_request.body if token_request.json_encoded else None,
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning(
            "%s OAuth token exchange network error for app %d: %s",
            app.name,
            app.id,
            exc,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"Could not reach {app.name} to complete OAuth.",
        )

    if 300 <= response.status_code < 400:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.name} redirected its OAuth token request.",
        )

    try:
        response_data = response.json()
    except ValueError:
        logger.warning(
            "%s OAuth token response was not JSON (status=%d)",
            app.name,
            response.status_code,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.name} returned a non-JSON response during OAuth.",
        )

    if not isinstance(response_data, dict):
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.name} returned an invalid token response during OAuth.",
        )

    error = provider.classify_token_response(response, response_data)
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

    # Stamp an absolute `expires_at` now so the lazy-refresh path can later
    # decide staleness without "when was this written" bookkeeping.
    credentials = provider.extract_credentials(response_data)
    access_token = credentials.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.name} returned an invalid access token during OAuth.",
        )
    stored_credentials = stamp_expires_at(credentials, datetime.now(timezone.utc))

    # The grant is authoritative and captured only here (a refresh can't change
    # it); None when the provider gives no signal.
    granted_scopes = provider.extract_granted_scopes(response_data)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=stored_credentials,
        granted_scopes=granted_scopes,
    )

    # Authenticating opens this user's per-user gate; refresh their sandboxes so
    # the now-usable skill bundle lands
    push_skills_for_users({user.id}, db_session)
    db_session.commit()

    return OAuthCallbackResponse(
        success=True, external_app_id=app.id, return_path=payload.return_path
    )
