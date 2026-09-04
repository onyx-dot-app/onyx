"""API endpoints for OAuth configuration management."""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import (
    OAuthTokenManager,
    conflicting_authorization_params,
)
from onyx.auth.permissions import has_global_permission, require_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import OAuthConfig, User
from onyx.db.oauth_config import (
    create_oauth_config,
    delete_oauth_config,
    delete_user_oauth_token,
    get_oauth_config,
    get_oauth_configs,
    get_tools_by_oauth_config,
    update_oauth_config,
    upsert_user_oauth_token,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
from onyx.server.features.oauth_config.models import (
    OAuthCallbackResponse,
    OAuthConfigCreate,
    OAuthConfigSnapshot,
    OAuthConfigUpdate,
    OAuthInitiateRequest,
    OAuthInitiateResponse,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/oauth-config")
router = APIRouter(prefix="/oauth-config")

_OAUTH_CALLBACK_PATH = "/oauth-config/callback"


class _OAuthConfigAttemptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    oauth_config_id: int
    return_path: SafeOAuthReturnPath
    configuration_fingerprint: OAuthConfigurationFingerprint
    code_verifier: PKCECodeVerifier | None = None


_AUTHORIZATION_ATTEMPTS = AuthorizationAttemptStore(
    cache_backend_provider=lambda: get_cache_backend(),
    namespace="oauth-config",
    payload_type=_OAuthConfigAttemptPayload,
)


def _oauth_callback_url() -> str:
    return f"{WEB_DOMAIN}{_OAUTH_CALLBACK_PATH}"


def _oauth_config_fingerprint(oauth_config: OAuthConfig) -> str:
    return canonical_json_fingerprint(
        {
            "redirect_uri": _oauth_callback_url(),
            "flow": OAuthTokenManager.flow_params(oauth_config).model_dump(mode="json"),
            "supports_pkce": oauth_config.supports_pkce,
        },
    )


def _validate_additional_authorization_params(oauth_config: OAuthConfig) -> None:
    reserved = conflicting_authorization_params(oauth_config.additional_params)
    if reserved:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth additional parameters cannot override: "
            f"{', '.join(sorted(reserved))}",
        )


def _oauth_config_to_snapshot(
    oauth_config: OAuthConfig, db_session: Session
) -> OAuthConfigSnapshot:
    """Convert OAuthConfig model to API snapshot."""
    tools = get_tools_by_oauth_config(oauth_config.id, db_session)
    return OAuthConfigSnapshot(
        id=oauth_config.id,
        name=oauth_config.name,
        authorization_url=oauth_config.authorization_url,
        token_url=oauth_config.token_url,
        scopes=oauth_config.scopes,
        supports_pkce=oauth_config.supports_pkce,
        has_client_credentials=bool(
            oauth_config.client_id and oauth_config.client_secret
        ),
        tool_count=len(tools),
        created_at=oauth_config.created_at,
        updated_at=oauth_config.updated_at,
    )


"""Admin endpoints for OAuth configuration management"""


def _assert_can_manage_oauth_config(
    oauth_config: OAuthConfig, user: User, db_session: Session
) -> None:
    """Owner-or-admin gate: a global actions-admin manages any OAuth config; a scoped manager
    manages one only when they own every action referencing it — editing shared credentials
    would otherwise affect the other creators."""
    if has_global_permission(user, Permission.MANAGE_ACTIONS):
        return
    tools = get_tools_by_oauth_config(oauth_config.id, db_session)
    if tools and all(tool.user_id == user.id for tool in tools):
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You can only manage OAuth configurations for actions that you created.",
    )


@admin_router.post("/create")
def create_oauth_config_endpoint(
    oauth_data: OAuthConfigCreate,
    db_session: Session = Depends(get_session),
    _: User = Depends(require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)),
) -> OAuthConfigSnapshot:
    """Create a new OAuth configuration. A scoped manager may create one and link it to an
    action they created; get/update/delete are then owner-or-admin."""
    try:
        oauth_config = create_oauth_config(
            name=oauth_data.name,
            authorization_url=oauth_data.authorization_url,
            token_url=oauth_data.token_url,
            client_id=oauth_data.client_id,
            client_secret=oauth_data.client_secret,
            scopes=oauth_data.scopes,
            additional_params=oauth_data.additional_params,
            db_session=db_session,
            supports_pkce=oauth_data.supports_pkce,
        )
        return _oauth_config_to_snapshot(oauth_config, db_session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.get("")
def list_oauth_configs(
    db_session: Session = Depends(get_session),
    _: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),
) -> list[OAuthConfigSnapshot]:
    """List all OAuth configurations (admin only)."""
    oauth_configs = get_oauth_configs(db_session)
    return [_oauth_config_to_snapshot(config, db_session) for config in oauth_configs]


@admin_router.get("/{oauth_config_id}")
def get_oauth_config_endpoint(
    oauth_config_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> OAuthConfigSnapshot:
    """Retrieve a single OAuth configuration (owner or admin)."""
    oauth_config = get_oauth_config(oauth_config_id, db_session)
    if not oauth_config:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {oauth_config_id} not found",
        )
    _assert_can_manage_oauth_config(oauth_config, user, db_session)
    return _oauth_config_to_snapshot(oauth_config, db_session)


@admin_router.put("/{oauth_config_id}")
def update_oauth_config_endpoint(
    oauth_config_id: int,
    oauth_data: OAuthConfigUpdate,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> OAuthConfigSnapshot:
    """Update an OAuth configuration (owner or admin)."""
    existing_config = get_oauth_config(oauth_config_id, db_session)
    if not existing_config:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {oauth_config_id} not found",
        )
    _assert_can_manage_oauth_config(existing_config, user, db_session)
    try:
        updated_config = update_oauth_config(
            oauth_config_id=oauth_config_id,
            db_session=db_session,
            name=oauth_data.name,
            authorization_url=oauth_data.authorization_url,
            token_url=oauth_data.token_url,
            client_id=oauth_data.client_id,
            client_secret=oauth_data.client_secret,
            scopes=oauth_data.scopes,
            additional_params=oauth_data.additional_params,
            supports_pkce=oauth_data.supports_pkce,
            clear_client_id=oauth_data.clear_client_id,
            clear_client_secret=oauth_data.clear_client_secret,
        )
        return _oauth_config_to_snapshot(updated_config, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.delete("/{oauth_config_id}")
def delete_oauth_config_endpoint(
    oauth_config_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> dict[str, str]:
    """Delete an OAuth configuration (owner or admin)."""
    existing_config = get_oauth_config(oauth_config_id, db_session)
    if not existing_config:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {oauth_config_id} not found",
        )
    _assert_can_manage_oauth_config(existing_config, user, db_session)
    try:
        delete_oauth_config(oauth_config_id, db_session)
        return {"message": "OAuth configuration deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


"""User endpoints for OAuth flow"""


@router.post("/initiate")
def initiate_oauth_flow(
    request: OAuthInitiateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> OAuthInitiateResponse:
    """
    Initiate OAuth flow for the current user.

    Returns an authorization URL that the frontend should redirect the user to.
    """
    # Get OAuth config
    oauth_config = get_oauth_config(request.oauth_config_id, db_session)
    if not oauth_config:
        raise HTTPException(
            status_code=404,
            detail=f"OAuth config with id {request.oauth_config_id} not found",
        )

    _validate_additional_authorization_params(oauth_config)
    code_verifier: str | None = None
    code_challenge: str | None = None
    if oauth_config.supports_pkce:
        code_verifier, code_challenge = generate_pkce_pair()
    state = generate_authorization_state()

    authorization_url = OAuthTokenManager.build_authorization_url(
        oauth_config,
        _oauth_callback_url(),
        state,
        code_challenge=code_challenge,
    )
    _AUTHORIZATION_ATTEMPTS.store(
        owner_id=str(user.id),
        state=state,
        payload=_OAuthConfigAttemptPayload(
            oauth_config_id=oauth_config.id,
            return_path=request.return_path,
            configuration_fingerprint=_oauth_config_fingerprint(oauth_config),
            code_verifier=code_verifier,
        ),
    )

    return OAuthInitiateResponse(authorization_url=authorization_url, state=state)


@router.post("/callback")
def handle_oauth_callback(
    code: str,
    state: str,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> OAuthCallbackResponse:
    """
    Handle OAuth callback after user authorizes the application.

    Exchanges the authorization code for an access token and stores it.
    Accepts code and state as query parameters (standard OAuth flow).
    """
    attempt = _AUTHORIZATION_ATTEMPTS.consume(owner_id=str(user.id), state=state)
    payload = attempt.payload

    oauth_config = get_oauth_config(payload.oauth_config_id, db_session)
    if not oauth_config:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {payload.oauth_config_id} not found",
        )
    if not secrets.compare_digest(
        payload.configuration_fingerprint,
        _oauth_config_fingerprint(oauth_config),
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth configuration changed while authorization was pending.",
        )

    try:
        # Exchange code for token
        token_manager = OAuthTokenManager(oauth_config, user.id, db_session)
        token_data = token_manager.exchange_code_for_token(
            code,
            _oauth_callback_url(),
            code_verifier=payload.code_verifier,
        )

        # Store token
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Return success with redirect
        return OAuthCallbackResponse(
            redirect_url=payload.return_path,
        )

    except ValueError as e:
        logger.error("OAuth callback error: %s", e)
        return OAuthCallbackResponse(
            redirect_url="/chat",
            error=str(e),
        )
    except Exception as e:
        logger.error("Unexpected OAuth callback error: %s", e)
        return OAuthCallbackResponse(
            redirect_url="/chat",
            error="An unexpected error occurred during OAuth callback",
        )


@router.delete("/{oauth_config_id}/token")
def revoke_oauth_token(
    oauth_config_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> dict[str, str]:
    """
    Revoke (delete) the current user's OAuth token for a specific OAuth config.
    """
    try:
        delete_user_oauth_token(oauth_config_id, user.id, db_session)
        return {"message": "OAuth token revoked successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
