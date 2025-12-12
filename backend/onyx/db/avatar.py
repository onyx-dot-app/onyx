"""
Avatar database operations.

This module provides CRUD operations for Avatar, AvatarPermissionRequest,
and AvatarQuery models.
"""

from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.db.enums import AvatarPermissionRequestStatus
from onyx.db.enums import AvatarQueryMode
from onyx.db.models import Avatar
from onyx.db.models import AvatarPermissionRequest
from onyx.db.models import AvatarQuery
from onyx.db.models import User


# Default expiration for permission requests (in days)
DEFAULT_REQUEST_EXPIRY_DAYS = 7


# ============================================================================
# Avatar CRUD Operations
# ============================================================================


def create_avatar_for_user(
    user_id: UUID,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
) -> Avatar:
    """Create a new avatar for a user.

    Args:
        user_id: The ID of the user to create an avatar for
        db_session: Database session
        name: Optional display name for the avatar
        description: Optional description for the avatar

    Returns:
        The created Avatar instance
    """
    avatar = Avatar(
        user_id=user_id,
        name=name,
        description=description,
        is_enabled=True,
        default_query_mode=AvatarQueryMode.OWNED_DOCUMENTS,
        allow_accessible_mode=True,
        show_query_in_request=True,
        max_requests_per_day=100,
    )
    db_session.add(avatar)
    db_session.flush()
    return avatar


async def create_avatar_for_user_async(
    user_id: UUID,
    db_session: AsyncSession,
    name: str | None = None,
    description: str | None = None,
) -> Avatar:
    """Create a new avatar for a user (async version).

    Args:
        user_id: The ID of the user to create an avatar for
        db_session: Async database session
        name: Optional display name for the avatar
        description: Optional description for the avatar

    Returns:
        The created Avatar instance
    """
    avatar = Avatar(
        user_id=user_id,
        name=name,
        description=description,
        is_enabled=True,
        default_query_mode=AvatarQueryMode.OWNED_DOCUMENTS,
        allow_accessible_mode=True,
        show_query_in_request=True,
        max_requests_per_day=100,
    )
    db_session.add(avatar)
    await db_session.flush()
    return avatar


def get_avatar_by_id(avatar_id: int, db_session: Session) -> Avatar | None:
    """Get an avatar by its ID."""
    return db_session.query(Avatar).filter(Avatar.id == avatar_id).first()


def get_avatar_by_user_id(user_id: UUID, db_session: Session) -> Avatar | None:
    """Get an avatar by its user ID."""
    return db_session.query(Avatar).filter(Avatar.user_id == user_id).first()


def get_all_enabled_avatars(
    db_session: Session,
    exclude_user_id: UUID | None = None,
) -> list[Avatar]:
    """Get all enabled avatars, optionally excluding a specific user's avatar."""
    query = db_session.query(Avatar).filter(Avatar.is_enabled == True)  # noqa: E712
    if exclude_user_id:
        query = query.filter(Avatar.user_id != exclude_user_id)
    return query.all()


def update_avatar(
    avatar_id: int,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    is_enabled: bool | None = None,
    default_query_mode: AvatarQueryMode | None = None,
    allow_accessible_mode: bool | None = None,
    auto_approve_rules: dict | None = None,
    show_query_in_request: bool | None = None,
    max_requests_per_day: int | None = None,
) -> Avatar | None:
    """Update an avatar's settings.

    Only non-None values will be updated.
    """
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar:
        return None

    if name is not None:
        avatar.name = name
    if description is not None:
        avatar.description = description
    if is_enabled is not None:
        avatar.is_enabled = is_enabled
    if default_query_mode is not None:
        avatar.default_query_mode = default_query_mode
    if allow_accessible_mode is not None:
        avatar.allow_accessible_mode = allow_accessible_mode
    if auto_approve_rules is not None:
        avatar.auto_approve_rules = auto_approve_rules
    if show_query_in_request is not None:
        avatar.show_query_in_request = show_query_in_request
    if max_requests_per_day is not None:
        avatar.max_requests_per_day = max_requests_per_day

    db_session.flush()
    return avatar


def delete_avatar(avatar_id: int, db_session: Session) -> bool:
    """Delete an avatar by ID."""
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar:
        return False
    db_session.delete(avatar)
    db_session.flush()
    return True


# ============================================================================
# Avatar Permission Request Operations
# ============================================================================


def create_permission_request(
    avatar_id: int,
    requester_id: UUID,
    query_text: str | None,
    db_session: Session,
    chat_session_id: UUID | None = None,
    chat_message_id: int | None = None,
    cached_answer: str | None = None,
    cached_search_doc_ids: list[int] | None = None,
    answer_quality_score: float | None = None,
    expires_in_days: int = DEFAULT_REQUEST_EXPIRY_DAYS,
) -> AvatarPermissionRequest:
    """Create a new permission request."""
    request = AvatarPermissionRequest(
        avatar_id=avatar_id,
        requester_id=requester_id,
        query_text=query_text,
        chat_session_id=chat_session_id,
        chat_message_id=chat_message_id,
        cached_answer=cached_answer,
        cached_search_doc_ids=cached_search_doc_ids,
        answer_quality_score=answer_quality_score,
        status=AvatarPermissionRequestStatus.PENDING,
        expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
    )
    db_session.add(request)
    db_session.flush()
    return request


def get_permission_request_by_id(
    request_id: int, db_session: Session
) -> AvatarPermissionRequest | None:
    """Get a permission request by ID."""
    return (
        db_session.query(AvatarPermissionRequest)
        .filter(AvatarPermissionRequest.id == request_id)
        .first()
    )


def get_pending_requests_for_avatar_owner(
    user_id: UUID, db_session: Session
) -> list[AvatarPermissionRequest]:
    """Get all pending permission requests for a user's avatar."""
    return (
        db_session.query(AvatarPermissionRequest)
        .join(Avatar, AvatarPermissionRequest.avatar_id == Avatar.id)
        .filter(
            Avatar.user_id == user_id,
            AvatarPermissionRequest.status == AvatarPermissionRequestStatus.PENDING,
            AvatarPermissionRequest.expires_at > datetime.utcnow(),
        )
        .order_by(AvatarPermissionRequest.created_at.desc())
        .all()
    )


def get_permission_requests_by_requester(
    requester_id: UUID,
    db_session: Session,
    status: AvatarPermissionRequestStatus | None = None,
) -> list[AvatarPermissionRequest]:
    """Get all permission requests made by a user."""
    query = db_session.query(AvatarPermissionRequest).filter(
        AvatarPermissionRequest.requester_id == requester_id
    )
    if status:
        query = query.filter(AvatarPermissionRequest.status == status)
    return query.order_by(AvatarPermissionRequest.created_at.desc()).all()


def approve_permission_request(
    request_id: int, db_session: Session
) -> AvatarPermissionRequest | None:
    """Approve a permission request."""
    request = get_permission_request_by_id(request_id, db_session)
    if not request or request.status != AvatarPermissionRequestStatus.PENDING:
        return None

    request.status = AvatarPermissionRequestStatus.APPROVED
    request.resolved_at = datetime.utcnow()
    db_session.flush()
    return request


def deny_permission_request(
    request_id: int,
    db_session: Session,
    denial_reason: str | None = None,
) -> AvatarPermissionRequest | None:
    """Deny a permission request."""
    request = get_permission_request_by_id(request_id, db_session)
    if not request or request.status != AvatarPermissionRequestStatus.PENDING:
        return None

    request.status = AvatarPermissionRequestStatus.DENIED
    request.denial_reason = denial_reason
    request.resolved_at = datetime.utcnow()
    db_session.flush()
    return request


def expire_old_permission_requests(db_session: Session) -> int:
    """Mark all expired permission requests as expired.

    Returns the number of requests that were expired.
    """
    expired_count = (
        db_session.query(AvatarPermissionRequest)
        .filter(
            AvatarPermissionRequest.status == AvatarPermissionRequestStatus.PENDING,
            AvatarPermissionRequest.expires_at <= datetime.utcnow(),
        )
        .update(
            {
                AvatarPermissionRequest.status: AvatarPermissionRequestStatus.EXPIRED,
                AvatarPermissionRequest.resolved_at: datetime.utcnow(),
            }
        )
    )
    db_session.flush()
    return expired_count


# ============================================================================
# Avatar Query Operations (Rate Limiting & Analytics)
# ============================================================================


def log_avatar_query(
    avatar_id: int,
    requester_id: UUID,
    query_mode: AvatarQueryMode,
    query_text: str,
    db_session: Session,
) -> AvatarQuery:
    """Log an avatar query for rate limiting and analytics."""
    query = AvatarQuery(
        avatar_id=avatar_id,
        requester_id=requester_id,
        query_mode=query_mode,
        query_text=query_text,
    )
    db_session.add(query)
    db_session.flush()
    return query


def get_avatar_query_count_today(
    avatar_id: int,
    requester_id: UUID,
    db_session: Session,
) -> int:
    """Get the number of queries made to an avatar by a user today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db_session.query(AvatarQuery)
        .filter(
            AvatarQuery.avatar_id == avatar_id,
            AvatarQuery.requester_id == requester_id,
            AvatarQuery.created_at >= today_start,
        )
        .count()
    )


def check_rate_limit(
    avatar_id: int,
    requester_id: UUID,
    db_session: Session,
) -> bool:
    """Check if a requester has exceeded the rate limit for an avatar.

    Returns True if the request is allowed, False if rate limited.
    """
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar or not avatar.max_requests_per_day:
        return True

    query_count = get_avatar_query_count_today(avatar_id, requester_id, db_session)
    return query_count < avatar.max_requests_per_day


# ============================================================================
# Auto-Approval Logic
# ============================================================================


def should_auto_approve(
    avatar: Avatar,
    requester: User,
) -> bool:
    """Check if a request should be auto-approved based on avatar's rules.

    Auto-approve rules format:
    {
        "user_ids": ["uuid1", "uuid2"],
        "group_ids": ["group1", "group2"],
        "all_users": false
    }
    """
    if not avatar.auto_approve_rules:
        return False

    rules = avatar.auto_approve_rules

    # Check if all users are auto-approved
    if rules.get("all_users", False):
        return True

    # Check if requester is in the user whitelist
    user_ids = rules.get("user_ids", [])
    if str(requester.id) in user_ids:
        return True

    # Check if requester is in any of the whitelisted groups
    # Note: This would need integration with the UserGroup system
    # group_ids = rules.get("group_ids", [])
    # if group_ids:
    #     # TODO: Check if user is member of any whitelisted group
    #     pass

    return False
