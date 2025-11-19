import datetime
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import Date
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessageFeedback
from onyx.db.models import ChatSession
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.models import UserRole


def fetch_query_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, int, datetime.date]]:
    stmt = (
        select(
            func.count(ChatMessage.id),
            func.sum(case((ChatMessageFeedback.is_positive, 1), else_=0)),
            func.sum(
                case(
                    (ChatMessageFeedback.is_positive == False, 1), else_=0  # noqa: E712
                )
            ),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
            isouter=True,
        )
        .where(
            ChatMessage.time_sent >= start,
        )
        .where(
            ChatMessage.time_sent <= end,
        )
        .where(ChatMessage.message_type == MessageType.ASSISTANT)
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return db_session.execute(stmt).all()  # type: ignore


def fetch_per_user_query_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, int, datetime.date, UUID]]:
    stmt = (
        select(
            func.count(ChatMessage.id),
            func.sum(case((ChatMessageFeedback.is_positive, 1), else_=0)),
            func.sum(
                case(
                    (ChatMessageFeedback.is_positive == False, 1), else_=0  # noqa: E712
                )
            ),
            cast(ChatMessage.time_sent, Date),
            ChatSession.user_id,
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        # Include chats that have no explicit feedback instead of dropping them
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
            isouter=True,
        )
        .where(
            ChatMessage.time_sent >= start,
        )
        .where(
            ChatMessage.time_sent <= end,
        )
        .where(ChatMessage.message_type == MessageType.ASSISTANT)
        .group_by(cast(ChatMessage.time_sent, Date), ChatSession.user_id)
        .order_by(cast(ChatMessage.time_sent, Date), ChatSession.user_id)
    )

    return db_session.execute(stmt).all()  # type: ignore


def fetch_onyxbot_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, datetime.date]]:
    """Gets the:
    Date of each set of aggregated statistics
    Number of OnyxBot Queries (Chat Sessions)
    Number of instances of Negative feedback OR Needing additional help
        (only counting the last feedback)
    """
    # Get every chat session in the time range which is a Onyxbot flow
    # along with the first Assistant message which is the response to the user question.
    # Generally there should not be more than one AI message per chat session of this type
    subquery_first_ai_response = (
        db_session.query(
            ChatMessage.chat_session_id.label("chat_session_id"),
            func.min(ChatMessage.id).label("chat_message_id"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatSession.time_created >= start,
            ChatSession.time_created <= end,
            ChatSession.onyxbot_flow.is_(True),
        )
        .where(
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(ChatMessage.chat_session_id)
        .subquery()
    )

    # Get the chat message ids and most recent feedback for each of those chat messages,
    # not including the messages that have no feedback
    subquery_last_feedback = (
        db_session.query(
            ChatMessageFeedback.chat_message_id.label("chat_message_id"),
            func.max(ChatMessageFeedback.id).label("max_feedback_id"),
        )
        .group_by(ChatMessageFeedback.chat_message_id)
        .subquery()
    )

    results = (
        db_session.query(
            func.count(ChatSession.id).label("total_sessions"),
            # Need to explicitly specify this as False to handle the NULL case so the cases without
            # feedback aren't counted against Onyxbot
            func.sum(
                case(
                    (
                        or_(
                            ChatMessageFeedback.is_positive.is_(False),
                            ChatMessageFeedback.required_followup.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("negative_answer"),
            cast(ChatSession.time_created, Date).label("session_date"),
        )
        .join(
            subquery_first_ai_response,
            ChatSession.id == subquery_first_ai_response.c.chat_session_id,
        )
        # Combine the chat sessions with latest feedback to get the latest feedback for the first AI
        # message of the chat session where the chat session is Onyxbot type and within the time
        # range specified. Left/outer join used here to ensure that if no feedback, a null is used
        # for the feedback id
        .outerjoin(
            subquery_last_feedback,
            subquery_first_ai_response.c.chat_message_id
            == subquery_last_feedback.c.chat_message_id,
        )
        # Join the actual feedback table to get the feedback info for the sums
        # Outer join because the "last feedback" may be null
        .outerjoin(
            ChatMessageFeedback,
            ChatMessageFeedback.id == subquery_last_feedback.c.max_feedback_id,
        )
        .group_by(cast(ChatSession.time_created, Date))
        .order_by(cast(ChatSession.time_created, Date))
        .all()
    )

    return [tuple(row) for row in results]


def fetch_persona_message_analytics(
    db_session: Session,
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """Gets the daily message counts for a specific persona within the given time range."""
    query = (
        select(
            func.count(ChatMessage.id),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            or_(
                ChatMessage.alternate_assistant_id == persona_id,
                ChatSession.persona_id == persona_id,
            ),
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_persona_unique_users(
    db_session: Session,
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """Gets the daily unique user counts for a specific persona within the given time range."""
    query = (
        select(
            func.count(func.distinct(ChatSession.user_id)),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            or_(
                ChatMessage.alternate_assistant_id == persona_id,
                ChatSession.persona_id == persona_id,
            ),
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_message_analytics(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """
    Gets the daily message counts for a specific assistant in the given time range.
    """
    query = (
        select(
            func.count(ChatMessage.id),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            or_(
                ChatMessage.alternate_assistant_id == assistant_id,
                ChatSession.persona_id == assistant_id,
            ),
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_unique_users(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """
    Gets the daily unique user counts for a specific assistant in the given time range.
    """
    query = (
        select(
            func.count(func.distinct(ChatSession.user_id)),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            or_(
                ChatMessage.alternate_assistant_id == assistant_id,
                ChatSession.persona_id == assistant_id,
            ),
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_unique_users_total(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> int:
    """
    Gets the total number of distinct users who have sent or received messages from
    the specified assistant in the given time range.
    """
    query = (
        select(func.count(func.distinct(ChatSession.user_id)))
        .select_from(ChatMessage)
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            or_(
                ChatMessage.alternate_assistant_id == assistant_id,
                ChatSession.persona_id == assistant_id,
            ),
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )

    result = db_session.execute(query).scalar()
    return result if result else 0


# Users can view assistant stats if they created the persona,
# or if they are an admin
def user_can_view_assistant_stats(
    db_session: Session, user: User | None, assistant_id: int
) -> bool:
    # If user is None and auth is disabled, assume the user is an admin

    if user is None or user.role == UserRole.ADMIN:
        return True

    # Check if the user created the persona
    stmt = select(Persona).where(
        and_(Persona.id == assistant_id, Persona.user_id == user.id)
    )

    persona = db_session.execute(stmt).scalar_one_or_none()
    return persona is not None
