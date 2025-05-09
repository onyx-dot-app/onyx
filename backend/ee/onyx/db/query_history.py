from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import asc
from sqlalchemy import BinaryExpression
from sqlalchemy import ColumnElement
from sqlalchemy import desc
from sqlalchemy import distinct
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session
from sqlalchemy.sql import case
from sqlalchemy.sql import func
from sqlalchemy.sql import select
from sqlalchemy.sql.expression import literal
from sqlalchemy.sql.expression import UnaryExpression

from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from onyx.configs.constants import QAFeedbackType
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessageFeedback
from onyx.db.models import ChatSession
from onyx.db.models import TaskQueueState
from onyx.db.tasks import get_all_tasks_with_prefix


def _build_filter_conditions(
    start_time: datetime | None,
    end_time: datetime | None,
    feedback_filter: QAFeedbackType | None,
) -> list[ColumnElement]:
    """
    Helper function to build all filter conditions for chat sessions.
    Filters by start and end time, feedback type, and any sessions without messages.
    start_time: Date from which to filter
    end_time: Date to which to filter
    feedback_filter: Feedback type to filter by
    Returns: List of filter conditions
    """
    conditions = []

    if start_time is not None:
        conditions.append(ChatSession.time_created >= start_time)
    if end_time is not None:
        conditions.append(ChatSession.time_created <= end_time)

    if feedback_filter is not None:
        feedback_subq = (
            select(ChatMessage.chat_session_id)
            .join(ChatMessageFeedback)
            .group_by(ChatMessage.chat_session_id)
            .having(
                case(
                    (
                        case(
                            {literal(feedback_filter == QAFeedbackType.LIKE): True},
                            else_=False,
                        ),
                        func.bool_and(ChatMessageFeedback.is_positive),
                    ),
                    (
                        case(
                            {literal(feedback_filter == QAFeedbackType.DISLIKE): True},
                            else_=False,
                        ),
                        func.bool_and(func.not_(ChatMessageFeedback.is_positive)),
                    ),
                    else_=func.bool_or(ChatMessageFeedback.is_positive)
                    & func.bool_or(func.not_(ChatMessageFeedback.is_positive)),
                )
            )
        )
        conditions.append(ChatSession.id.in_(feedback_subq))

    return conditions


def get_total_filtered_chat_sessions_count(
    db_session: Session,
    start_time: datetime | None,
    end_time: datetime | None,
    feedback_filter: QAFeedbackType | None,
) -> int:
    conditions = _build_filter_conditions(start_time, end_time, feedback_filter)
    stmt = (
        select(func.count(distinct(ChatSession.id)))
        .select_from(ChatSession)
        .filter(*conditions)
    )
    return db_session.scalar(stmt) or 0


def get_page_of_chat_sessions(
    start_time: datetime | None,
    end_time: datetime | None,
    db_session: Session,
    page_num: int,
    page_size: int,
    feedback_filter: QAFeedbackType | None = None,
) -> Sequence[ChatSession]:
    conditions = _build_filter_conditions(start_time, end_time, feedback_filter)

    subquery = (
        select(ChatSession.id)
        .filter(*conditions)
        .order_by(desc(ChatSession.time_created), ChatSession.id)
        .limit(page_size)
        .offset(page_num * page_size)
        .subquery()
    )

    stmt = (
        select(ChatSession)
        .join(subquery, ChatSession.id == subquery.c.id)
        .outerjoin(ChatMessage, ChatSession.id == ChatMessage.chat_session_id)
        .options(
            joinedload(ChatSession.user),
            joinedload(ChatSession.persona),
            contains_eager(ChatSession.messages).joinedload(
                ChatMessage.chat_message_feedbacks
            ),
        )
        .order_by(
            desc(ChatSession.time_created),
            ChatSession.id,
            asc(ChatMessage.id),  # Ensure chronological message order
        )
    )

    return db_session.scalars(stmt).unique().all()


def fetch_chat_sessions_eagerly_by_time(
    start: datetime,
    end: datetime,
    db_session: Session,
    limit: int | None = 500,
    initial_time: datetime | None = None,
) -> list[ChatSession]:
    """Sorted by oldest to newest, then by message id"""

    asc_time_order: UnaryExpression = asc(ChatSession.time_created)
    message_order: UnaryExpression = asc(ChatMessage.id)

    filters: list[ColumnElement | BinaryExpression] = [
        ChatSession.time_created.between(start, end)
    ]

    if initial_time:
        filters.append(ChatSession.time_created > initial_time)

    subquery = (
        db_session.query(ChatSession.id, ChatSession.time_created)
        .filter(*filters)
        .order_by(asc_time_order)
        .limit(limit)
        .subquery()
    )

    query = (
        db_session.query(ChatSession)
        .join(subquery, ChatSession.id == subquery.c.id)
        .outerjoin(ChatMessage, ChatSession.id == ChatMessage.chat_session_id)
        .options(
            joinedload(ChatSession.user),
            joinedload(ChatSession.persona),
            contains_eager(ChatSession.messages).joinedload(
                ChatMessage.chat_message_feedbacks
            ),
        )
        .order_by(asc_time_order, message_order)
    )

    chat_sessions = query.all()

    return chat_sessions


def get_all_query_history_export_tasks(
    db_session: Session,
) -> list[TaskQueueState]:
    return get_all_tasks_with_prefix(db_session, QUERY_HISTORY_TASK_NAME_PREFIX)
