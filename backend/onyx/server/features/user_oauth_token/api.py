"""API endpoints for user OAuth token management."""

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import OAuthTokenManager
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.oauth_config import get_all_user_oauth_tokens

router = APIRouter(prefix="/user-oauth-token")


class OAuthTokenStatus(BaseModel):
    oauth_config_id: int
    expires_at: int | None  # Unix timestamp
    is_expired: bool


@router.get("/status")
def get_user_oauth_token_status(
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> list[OAuthTokenStatus]:
    """
    Get the OAuth token status for the current user across all OAuth configs.

    Returns information about which OAuth configs the user has authenticated with
    and whether their tokens are expired.
    """
    # disabled auth doesn't support user oauth tokens
    if user is None:
        return []

    user_tokens = get_all_user_oauth_tokens(user.id, db_session)
    return [
        OAuthTokenStatus(
            oauth_config_id=token.oauth_config_id,
            expires_at=OAuthTokenManager.token_expiration_time(token.token_data),
            is_expired=OAuthTokenManager.is_token_expired(token.token_data),
        )
        for token in user_tokens
    ]
