"""API endpoints for OAuth configuration management."""

import secrets
from collections.abc import Mapping

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import (
    exchange_oauth_code_for_token,
    oauth_flow_params_from_config,
    validate_oauth_endpoint_url,
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
from onyx.oauth.protocol import (
    OAuthFlowParams,
    build_oauth_authorization_url,
    validate_authorization_params,
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
from onyx.utils.url import SSRFException

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/oauth-config")
router = APIRouter(prefix="/oauth-config")

_OAUTH_CALLBACK_URL = f"{WEB_DOMAIN}/oauth-config/callback"


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


def _oauth_config_fingerprint(params: OAuthFlowParams, supports_pkce: bool) -> str:
    return canonical_json_fingerprint(
        {
            "redirect_uri": _OAUTH_CALLBACK_URL,
            "flow": params.model_dump(mode="json"),
            "supports_pkce": supports_pkce,
        },
    )


def _validate_authorization_configuration(
    authorization_url: str, additional_params: Mapping[str, object] | None
) -> None:
    try:
        validate_authorization_params(authorization_url, additional_params)
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error


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


def _validate_oauth_endpoint_urls(
    authorization_url: str | None, token_url: str | None
) -> None:
    for field, url in (
        ("authorization_url", authorization_url),
        ("token_url", token_url),
    ):
        if url is None:
            continue
        try:
            validate_oauth_endpoint_url(url, resolve_dns=False)
        except (SSRFException, ValueError) as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"Invalid {field}: {e}")


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
    _validate_oauth_endpoint_urls(oauth_data.authorization_url, oauth_data.token_url)
    _validate_authorization_configuration(
        oauth_data.authorization_url, oauth_data.additional_params
    )
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
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e


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
    _validate_oauth_endpoint_urls(
        oauth_data.authorization_url
        if oauth_data.authorization_url is not None
        else existing_config.authorization_url,
        oauth_data.token_url
        if oauth_data.token_url is not None
        else existing_config.token_url,
    )
    _validate_authorization_configuration(
        oauth_data.authorization_url
        if oauth_data.authorization_url is not None
        else existing_config.authorization_url,
        oauth_data.additional_params
        if oauth_data.additional_params is not None
        else existing_config.additional_params,
    )
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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e)) from e


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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e)) from e


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
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {request.oauth_config_id} not found",
        )

    _validate_authorization_configuration(
        oauth_config.authorization_url, oauth_config.additional_params
    )
    try:
        params = oauth_flow_params_from_config(oauth_config)
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
    code_verifier: str | None = None
    code_challenge: str | None = None
    if oauth_config.supports_pkce:
        code_verifier, code_challenge = generate_pkce_pair()
    state = generate_authorization_state()

    authorization_url = build_oauth_authorization_url(
        params,
        _OAUTH_CALLBACK_URL,
        state,
        code_challenge=code_challenge,
    )
    _AUTHORIZATION_ATTEMPTS.store(
        owner_id=str(user.id),
        state=state,
        payload=_OAuthConfigAttemptPayload(
            oauth_config_id=oauth_config.id,
            return_path=request.return_path,
            configuration_fingerprint=_oauth_config_fingerprint(
                params, oauth_config.supports_pkce
            ),
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
    try:
        params = oauth_flow_params_from_config(oauth_config)
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth configuration changed while authorization was pending.",
        ) from error
    if not secrets.compare_digest(
        payload.configuration_fingerprint,
        _oauth_config_fingerprint(params, oauth_config.supports_pkce),
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth configuration changed while authorization was pending.",
        )

    try:
        token_data = exchange_oauth_code_for_token(
            params,
            code,
            _OAUTH_CALLBACK_URL,
            code_verifier=payload.code_verifier,
        )
    except (requests.RequestException, SSRFException, ValueError) as error:
        logger.warning("OAuth token exchange failed (%s)", type(error).__name__)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "OAuth token exchange failed. Start authorization again.",
        ) from error

    upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)
    return OAuthCallbackResponse(redirect_url=payload.return_path)


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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e)) from e
