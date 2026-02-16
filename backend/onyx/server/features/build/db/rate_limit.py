"""Database queries for Build Mode rate limiting."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession


def count_user_messages_in_window(
    user_id: UUID,
    cutoff_time: datetime,
    db_session: Session,
) -> int:
    """
    Count USER messages for a user since cutoff_time.

    Args:
        user_id: The user's UUID
        cutoff_time: Only count messages created at or after this time
        db_session: Database session

    Returns:
        Number of USER messages in the time window
    """
    return (
        db_session.query(func.count(BuildMessage.id))
        .join(BuildSession, BuildMessage.session_id == BuildSession.id)
        .filter(
            BuildSession.user_id == user_id,
            BuildMessage.type == MessageType.USER,
            BuildMessage.created_at >= cutoff_time,
        )
        .scalar()
        or 0
    )


def count_user_messages_total(user_id: UUID, db_session: Session) -> int:
    """
    Count all USER messages for a user (lifetime total).

    Args:
        user_id: The user's UUID
        db_session: Database session

    Returns:
        Total number of USER messages
    """
    return (
        db_session.query(func.count(BuildMessage.id))
        .join(BuildSession, BuildMessage.session_id == BuildSession.id)
        .filter(
            BuildSession.user_id == user_id,
            BuildMessage.type == MessageType.USER,
        )
        .scalar()
        or 0
    )


def get_oldest_message_timestamp(
    user_id: UUID,
    cutoff_time: datetime,
    db_session: Session,
) -> datetime | None:
    """
    Get the timestamp of the oldest USER message in the time window.

    Used to calculate when the rate limit will reset (when the oldest
    message ages out of the rolling window).

    Args:
        user_id: The user's UUID
        cutoff_time: Only consider messages created at or after this time
        db_session: Database session

    Returns:
        Timestamp of oldest message in window, or None if no messages
    """
    return (
        db_session.query(BuildMessage.created_at)
        .join(BuildSession, BuildMessage.session_id == BuildSession.id)
        .filter(
            BuildSession.user_id == user_id,
            BuildMessage.type == MessageType.USER,
            BuildMessage.created_at >= cutoff_time,
        )
        .order_by(BuildMessage.created_at.asc())
        .limit(1)
        .scalar()
    )
