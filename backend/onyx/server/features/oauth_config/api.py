"""API endpoints for OAuth configuration management."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import OAuthTokenManager
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import OAuthConfig
from onyx.db.models import User
from onyx.db.oauth_config import create_oauth_config
from onyx.db.oauth_config import delete_oauth_config
from onyx.db.oauth_config import delete_user_oauth_token
from onyx.db.oauth_config import get_oauth_config
from onyx.db.oauth_config import get_oauth_configs
from onyx.db.oauth_config import get_tools_by_oauth_config
from onyx.db.oauth_config import update_oauth_config
from onyx.db.oauth_config import upsert_user_oauth_token
from onyx.federated_connectors.oauth_utils import generate_oauth_state
from onyx.federated_connectors.oauth_utils import verify_oauth_state
from onyx.server.features.oauth_config.models import OAuthCallbackResponse
from onyx.server.features.oauth_config.models import OAuthConfigCreate
from onyx.server.features.oauth_config.models import OAuthConfigSnapshot
from onyx.server.features.oauth_config.models import OAuthConfigUpdate
from onyx.server.features.oauth_config.models import OAuthInitiateRequest
from onyx.server.features.oauth_config.models import OAuthInitiateResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/oauth-config")
router = APIRouter(prefix="/oauth-config")


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
        has_client_credentials=bool(
            oauth_config.client_id and oauth_config.client_secret
        ),
        tool_count=len(tools),
        created_at=oauth_config.created_at,
        updated_at=oauth_config.updated_at,
    )


"""Admin endpoints for OAuth configuration management"""


@admin_router.post("/create")
def create_oauth_config_endpoint(
    oauth_data: OAuthConfigCreate,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> OAuthConfigSnapshot:
    """Create a new OAuth configuration (admin only)."""
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
        )
        return _oauth_config_to_snapshot(oauth_config, db_session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.get("")
def list_oauth_configs(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> list[OAuthConfigSnapshot]:
    """List all OAuth configurations (admin only)."""
    oauth_configs = get_oauth_configs(db_session)
    return [_oauth_config_to_snapshot(config, db_session) for config in oauth_configs]


@admin_router.put("/{oauth_config_id}")
def update_oauth_config_endpoint(
    oauth_config_id: int,
    oauth_data: OAuthConfigUpdate,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> OAuthConfigSnapshot:
    """Update an OAuth configuration (admin only)."""
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
    _: User | None = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    """Delete an OAuth configuration (admin only)."""
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
    user: User | None = Depends(current_user),
) -> OAuthInitiateResponse:
    """
    Initiate OAuth flow for the current user.

    Returns an authorization URL that the frontend should redirect the user to.
    """
    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # Get OAuth config
    oauth_config = get_oauth_config(request.oauth_config_id, db_session)
    if not oauth_config:
        raise HTTPException(
            status_code=404,
            detail=f"OAuth config with id {request.oauth_config_id} not found",
        )

    # Generate state parameter and store in Redis
    state = generate_oauth_state(
        federated_connector_id=request.oauth_config_id,
        user_id=str(user.id),
        redirect_uri=request.return_path,
        additional_data={"oauth_config_id": request.oauth_config_id},
    )

    # Build authorization URL
    redirect_uri = f"{WEB_DOMAIN}/oauth-config/callback"
    authorization_url = OAuthTokenManager.build_authorization_url(
        oauth_config, redirect_uri, state
    )

    return OAuthInitiateResponse(authorization_url=authorization_url, state=state)


@router.post("/callback")
def handle_oauth_callback(
    code: str,
    state: str,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> OAuthCallbackResponse:
    """
    Handle OAuth callback after user authorizes the application.

    Exchanges the authorization code for an access token and stores it.
    Accepts code and state as query parameters (standard OAuth flow).
    """
    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        # Verify state and retrieve session data
        session = verify_oauth_state(state)

        # Verify the user_id matches
        if str(user.id) != session.user_id:
            raise HTTPException(
                status_code=403, detail="User mismatch in OAuth callback"
            )

        # Extract oauth_config_id from session (stored during initiate)
        oauth_config_id = session.federated_connector_id

        # Get OAuth config
        oauth_config = get_oauth_config(oauth_config_id, db_session)
        if not oauth_config:
            raise HTTPException(
                status_code=404,
                detail=f"OAuth config with id {oauth_config_id} not found",
            )

        # Exchange code for token
        redirect_uri = f"{WEB_DOMAIN}/oauth-config/callback"
        token_manager = OAuthTokenManager(oauth_config, user.id, db_session)
        token_data = token_manager.exchange_code_for_token(code, redirect_uri)

        # Store token
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Return success with redirect
        return_path = session.redirect_uri or "/chat"
        return OAuthCallbackResponse(
            redirect_url=return_path,
        )

    except ValueError as e:
        logger.error(f"OAuth callback error: {e}")
        return OAuthCallbackResponse(
            redirect_url="/chat",
            error=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected OAuth callback error: {e}")
        return OAuthCallbackResponse(
            redirect_url="/chat",
            error="An unexpected error occurred during OAuth callback",
        )


@router.delete("/{oauth_config_id}/token")
def revoke_oauth_token(
    oauth_config_id: int,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict[str, str]:
    """
    Revoke (delete) the current user's OAuth token for a specific OAuth config.
    """
    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        delete_user_oauth_token(oauth_config_id, user.id, db_session)
        return {"message": "OAuth token revoked successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
