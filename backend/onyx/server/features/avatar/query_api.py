"""
Avatar query API endpoints.
"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.avatar import get_avatar_by_id
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.avatar.models import AvatarQueryRequest
from onyx.server.features.avatar.models import AvatarQueryResponse
from onyx.server.features.avatar.models import BroadcastQueryRequest
from onyx.server.features.avatar.models import BroadcastQueryResponse
from onyx.server.features.avatar.query_service import execute_avatar_query
from onyx.server.features.avatar.query_service import execute_broadcast_query
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/avatar/query")


@router.post("/single/{avatar_id}")
def query_single_avatar(
    avatar_id: int,
    request: AvatarQueryRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AvatarQueryResponse:
    """Query a single avatar."""
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Users cannot query their own avatar
    if avatar.user_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot query your own avatar",
        )

    response = execute_avatar_query(
        avatar_id=avatar_id,
        query=request.query,
        query_mode=request.query_mode,
        requester=user,
        db_session=db_session,
        chat_session_id=request.chat_session_id,
    )

    return response


@router.post("/broadcast")
def query_multiple_avatars(
    request: BroadcastQueryRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> BroadcastQueryResponse:
    """Query multiple avatars at once."""
    if not request.avatar_ids:
        raise HTTPException(status_code=400, detail="No avatar IDs provided")

    if len(request.avatar_ids) > 10:
        raise HTTPException(
            status_code=400,
            detail="Cannot query more than 10 avatars at once",
        )

    # Filter out the user's own avatar
    filtered_avatar_ids = []
    for avatar_id in request.avatar_ids:
        avatar = get_avatar_by_id(avatar_id, db_session)
        if avatar and avatar.user_id != user.id:
            filtered_avatar_ids.append(avatar_id)

    if not filtered_avatar_ids:
        raise HTTPException(
            status_code=400,
            detail="No valid avatars to query (you cannot query your own avatar)",
        )

    results = execute_broadcast_query(
        avatar_ids=filtered_avatar_ids,
        query=request.query,
        query_mode=request.query_mode,
        requester=user,
        db_session=db_session,
    )

    return BroadcastQueryResponse(results=results)
