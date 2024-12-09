import datetime
from typing import Literal

from sqlalchemy import asc
from sqlalchemy import BinaryExpression
from sqlalchemy import ColumnElement
from sqlalchemy import desc
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import UnaryExpression

from danswer.db.models import ChatMessage
from danswer.db.models import ChatSession

SortByOptions = Literal["time_sent"]


def fetch_chat_sessions_eagerly_by_time(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
    limit: int | None = 500,
    initial_time: datetime.datetime | None = None,
) -> list[ChatSession]:
    time_order: UnaryExpression = desc(ChatSession.time_created)
    message_order: UnaryExpression = asc(ChatMessage.id)

    filters: list[ColumnElement | BinaryExpression] = [
        ChatSession.time_created.between(start, end)
    ]

    if initial_time:
        filters.append(ChatSession.time_created > initial_time)

    subquery = (
        db_session.query(ChatSession.id, ChatSession.time_created)
        .filter(*filters)
        .order_by(ChatSession.id, time_order)
        .distinct(ChatSession.id)
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
        .order_by(time_order, message_order)
    )

    chat_sessions = query.all()

    return chat_sessions
