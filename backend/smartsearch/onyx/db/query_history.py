from collections.abc import Sequence
from datetime import datetime
from typing import List

from sqlalchemy import asc, BinaryExpression, ColumnElement, desc, distinct
from sqlalchemy.orm import Session, contains_eager, joinedload
from sqlalchemy.sql import case, func, select
from sqlalchemy.sql.expression import literal, UnaryExpression

from onyx.configs.constants import QAFeedbackType
from onyx.db.models import ChatMessage, ChatMessageFeedback, ChatSession


def _construct_time_filters(
    start_time: datetime | None, end_time: datetime | None
) -> List[ColumnElement]:
    """Формирует условия фильтрации по временным границам."""
    time_filters: List[ColumnElement] = []
    if start_time:
        time_filters.append(ChatSession.time_created >= start_time)
    if end_time:
        time_filters.append(ChatSession.time_created <= end_time)
    return time_filters


def _construct_feedback_filter(
    feedback_type: QAFeedbackType,
) -> BinaryExpression:
    """Создает подзапрос для фильтрации сессий по типу фидбека."""
    return select(ChatMessage.chat_session_id).join(
        ChatMessageFeedback
    ).group_by(
        ChatMessage.chat_session_id
    ).having(
        case(
            (
                case(
                    {literal(feedback_type == QAFeedbackType.LIKE): True},
                    else_=False,
                ),
                func.bool_and(ChatMessageFeedback.is_positive),
            ),
            (
                case(
                    {literal(feedback_type == QAFeedbackType.DISLIKE): True},
                    else_=False,
                ),
                func.bool_and(func.not_(ChatMessageFeedback.is_positive)),
            ),
            else_=func.bool_or(ChatMessageFeedback.is_positive)
            & func.bool_or(func.not_(ChatMessageFeedback.is_positive)),
        )
    )


def _build_filter_conditions(
    start_time: datetime | None,
    end_time: datetime | None,
    feedback_filter: QAFeedbackType | None,
) -> List[ColumnElement]:
    """
    Собирает все условия фильтрации для сессий чата.
    Учитывает временные рамки, тип фидбека и сессии без сообщений.
    """
    all_conditions: List[ColumnElement] = _construct_time_filters(
        start_time, end_time
    )

    if feedback_filter:
        feedback_query = _construct_feedback_filter(feedback_filter)
        all_conditions.append(ChatSession.id.in_(feedback_query))

    return all_conditions


def get_total_filtered_chat_sessions_count(
    db_session: Session,
    start_time: datetime | None,
    end_time: datetime | None,
    feedback_filter: QAFeedbackType | None,
) -> int:
    filter_clauses = _build_filter_conditions(
        start_time, end_time, feedback_filter
    )
    count_query = (
        select(func.count(distinct(ChatSession.id)))
        .select_from(ChatSession)
        .filter(*filter_clauses)
    )
    result = db_session.scalar(count_query)
    return result if result is not None else 0


def _create_pagination_subquery(
    filter_clauses: List[ColumnElement],
    offset: int,
    limit: int,
) -> UnaryExpression:
    """Генерирует подзапрос для пагинации ID сессий."""
    return (
        select(ChatSession.id)
        .filter(*filter_clauses)
        .order_by(desc(ChatSession.time_created), ChatSession.id)
        .limit(limit)
        .offset(offset)
        .subquery()
    )


def _apply_eager_loading(query: select) -> select:
    """Добавляет жадную загрузку связанных сущностей к запросу."""
    return query.options(
        joinedload(ChatSession.user),
        joinedload(ChatSession.persona),
        contains_eager(ChatSession.messages).joinedload(
            ChatMessage.chat_message_feedbacks
        ),
    )


def get_page_of_chat_sessions(
    start_time: datetime | None,
    end_time: datetime | None,
    db_session: Session,
    page_num: int,
    page_size: int,
    feedback_filter: QAFeedbackType | None = None,
) -> Sequence[ChatSession]:
    filter_clauses = _build_filter_conditions(
        start_time, end_time, feedback_filter
    )

    paginated_ids = _create_pagination_subquery(
        filter_clauses, page_num * page_size, page_size
    )

    base_query = (
        select(ChatSession)
        .join(paginated_ids, ChatSession.id == paginated_ids.c.id)
        .outerjoin(ChatMessage, ChatSession.id == ChatMessage.chat_session_id)
    )

    ordered_query = _apply_eager_loading(base_query).order_by(
        desc(ChatSession.time_created),
        ChatSession.id,
        asc(ChatMessage.id),  # Гарантирует хронологический порядок сообщений
    )

    return db_session.scalars(ordered_query).unique().all()


def _setup_time_based_filters(
    start: datetime, end: datetime, initial: datetime | None
) -> List[ColumnElement | BinaryExpression]:
    """Настраивает фильтры по временному диапазону с опциональным сдвигом."""
    base_filters: List[ColumnElement | BinaryExpression] = [
        ChatSession.time_created.between(start, end)
    ]
    if initial:
        base_filters.append(ChatSession.time_created > initial)
    return base_filters


def _generate_time_limited_subquery(
    session: Session,
    time_filters: List[ColumnElement | BinaryExpression],
    max_count: int | None,
) -> UnaryExpression:
    """Создает подзапрос для ограниченного выборки сессий по времени."""
    subq = (
        session.query(ChatSession.id, ChatSession.time_created)
        .filter(*time_filters)
        .order_by(asc(ChatSession.time_created))
    )
    if max_count:
        subq = subq.limit(max_count)
    return subq.subquery()


def fetch_chat_sessions_eagerly_by_time(
    start: datetime,
    end: datetime,
    db_session: Session,
    limit: int | None = 500,
    initial_time: datetime | None = None,
) -> list[ChatSession]:
    """
    Извлекает сессии чата в диапазоне времени с жадной загрузкой.
    Сортировка: от старых к новым, затем по ID сообщения.
    """
    time_ordering: UnaryExpression = asc(ChatSession.time_created)
    msg_ordering: UnaryExpression = asc(ChatMessage.id)

    time_constraints = _setup_time_based_filters(start, end, initial_time)

    limited_subquery = _generate_time_limited_subquery(
        db_session, time_constraints, limit
    )

    main_query = (
        db_session.query(ChatSession)
        .join(limited_subquery, ChatSession.id == limited_subquery.c.id)
        .outerjoin(ChatMessage, ChatSession.id == ChatMessage.chat_session_id)
    )

    fully_loaded_query = _apply_eager_loading(main_query).order_by(
        time_ordering, msg_ordering
    )

    return fully_loaded_query.all()
