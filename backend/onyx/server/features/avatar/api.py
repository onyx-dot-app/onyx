"""
Avatar management API endpoints.
"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.avatar import create_avatar_for_user
from onyx.db.avatar import get_all_enabled_avatars
from onyx.db.avatar import get_avatar_by_id
from onyx.db.avatar import get_avatar_by_user_id
from onyx.db.avatar import update_avatar
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.avatar.models import AvatarListItem
from onyx.server.features.avatar.models import AvatarSnapshot
from onyx.server.features.avatar.models import AvatarUpdateRequest
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/avatar")


@router.get("/me")
def get_my_avatar(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AvatarSnapshot:
    """Get the current user's avatar."""
    avatar = get_avatar_by_user_id(user.id, db_session)
    if not avatar:
        # Create avatar if it doesn't exist (for users created before the feature)
        avatar = create_avatar_for_user(
            user_id=user.id,
            db_session=db_session,
            name=None,
            description=None,
        )
        db_session.commit()

    return AvatarSnapshot.from_model(avatar)


@router.patch("/me")
def update_my_avatar(
    update_request: AvatarUpdateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AvatarSnapshot:
    """Update the current user's avatar settings."""
    avatar = get_avatar_by_user_id(user.id, db_session)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    updated_avatar = update_avatar(
        avatar_id=avatar.id,
        db_session=db_session,
        name=update_request.name,
        description=update_request.description,
        is_enabled=update_request.is_enabled,
        default_query_mode=update_request.default_query_mode,
        allow_accessible_mode=update_request.allow_accessible_mode,
        auto_approve_rules=update_request.auto_approve_rules,
        show_query_in_request=update_request.show_query_in_request,
        max_requests_per_day=update_request.max_requests_per_day,
    )

    if not updated_avatar:
        raise HTTPException(status_code=500, detail="Failed to update avatar")

    db_session.commit()
    return AvatarSnapshot.from_model(updated_avatar)


@router.get("/list")
def list_queryable_avatars(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[AvatarListItem]:
    """List all enabled avatars that can be queried, excluding the current user's avatar."""
    avatars = get_all_enabled_avatars(db_session, exclude_user_id=user.id)
    return [AvatarListItem.from_model(avatar) for avatar in avatars]


@router.get("/{avatar_id}")
def get_avatar(
    avatar_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AvatarSnapshot:
    """Get a specific avatar by ID."""
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if not avatar.is_enabled and avatar.user_id != user.id:
        raise HTTPException(status_code=404, detail="Avatar not found")

    return AvatarSnapshot.from_model(avatar)
