"""API endpoints for Personal Access Tokens."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.pat import create_pat
from onyx.db.pat import list_user_pats
from onyx.db.pat import revoke_pat
from onyx.server.pat.models import CreatedTokenResponse
from onyx.server.pat.models import CreateTokenRequest
from onyx.server.pat.models import TokenResponse
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/user/pats")


@router.get("")
def list_tokens(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[TokenResponse]:
    """List all active tokens for current user."""
    pats = list_user_pats(db_session, user.id)
    return [
        TokenResponse(
            id=pat.id,
            name=pat.name,
            token_display=pat.token_display,
            created_at=pat.created_at,
            expires_at=pat.expires_at,
            last_used_at=pat.last_used_at,
        )
        for pat in pats
    ]


@router.post("")
def create_token(
    request: CreateTokenRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreatedTokenResponse:
    """Create new personal access token for current user."""
    try:
        pat, raw_token = create_pat(
            db_session=db_session,
            user_id=user.id,
            name=request.name,
            expiration_days=request.expiration_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"User {user.email} created PAT '{request.name}'")

    return CreatedTokenResponse(
        id=pat.id,
        name=pat.name,
        token_display=pat.token_display,
        token=raw_token,  # ONLY time we return the raw token!
        created_at=pat.created_at,
        expires_at=pat.expires_at,
        last_used_at=pat.last_used_at,
    )


@router.delete("/{token_id}")
def delete_token(
    token_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Delete (revoke) personal access token. Only owner can revoke their own tokens."""
    success = revoke_pat(db_session, token_id, user.id)
    if not success:
        raise HTTPException(
            status_code=404, detail="Token not found or not owned by user"
        )

    logger.info(f"User {user.email} revoked token {token_id}")
    return {"message": "Token deleted successfully"}
