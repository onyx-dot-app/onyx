from typing import List
from typing import Optional
from typing import Tuple
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import union_all
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession


def search_chat_sessions(
    user_id: UUID | None,
    db_session: Session,
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    include_deleted: bool = False,
    include_onyxbot_flows: bool = False,
) -> Tuple[List[ChatSession], bool]:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.

    Returns a tuple of (chat_sessions, has_more)
    """
    offset = (page - 1) * page_size

    # If no search query, we use standard SQLAlchemy pagination
    if not query or not query.strip():
        stmt = select(ChatSession)
        if user_id:
            stmt = stmt.where(ChatSession.user_id == user_id)
        if not include_onyxbot_flows:
            stmt = stmt.where(ChatSession.onyxbot_flow.is_(False))
        if not include_deleted:
            stmt = stmt.where(ChatSession.deleted.is_(False))

        stmt = stmt.order_by(desc(ChatSession.time_created))

        # Apply pagination
        stmt = stmt.offset(offset).limit(page_size + 1)
        result = db_session.execute(stmt.options(joinedload(ChatSession.persona)))
        chat_sessions = result.scalars().all()

        has_more = len(chat_sessions) > page_size
        if has_more:
            chat_sessions = chat_sessions[:page_size]

        return list(chat_sessions), has_more

    words = query.lower().strip().split()

    # Message mach subquery
    message_matches = []
    for word in words:
        word_like = f"%{word}%"
        message_match: Select = (
            select(ChatMessage.chat_session_id, literal(1.0).label("search_rank"))
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(func.lower(ChatMessage.message).like(word_like))
        )

        if user_id:
            message_match = message_match.where(ChatSession.user_id == user_id)

        message_matches.append(message_match)

    if message_matches:
        message_matches_query = union_all(*message_matches).alias("message_matches")
    else:
        return [], False

    # Description matches
    description_match = select(
        ChatSession.id.label("chat_session_id"), literal(0.5).label("search_rank")
    ).where(func.lower(ChatSession.description).like(f"%{query.lower()}%"))

    if user_id:
        description_match = description_match.where(ChatSession.user_id == user_id)
    if not include_onyxbot_flows:
        description_match = description_match.where(ChatSession.onyxbot_flow.is_(False))
    if not include_deleted:
        description_match = description_match.where(ChatSession.deleted.is_(False))

    # Combine all match sources
    combined_matches = union_all(
        message_matches_query.select(), description_match
    ).alias("combined_matches")

    # Use CTE to group and get max rank
    session_ranks = (
        select(
            combined_matches.c.chat_session_id,
            func.max(combined_matches.c.search_rank).label("rank"),
        )
        .group_by(combined_matches.c.chat_session_id)
        .alias("session_ranks")
    )

    # Get ranked sessions with pagination
    ranked_query = (
        db_session.query(session_ranks.c.chat_session_id, session_ranks.c.rank)
        .order_by(desc(session_ranks.c.rank), session_ranks.c.chat_session_id)
        .offset(offset)
        .limit(page_size + 1)
    )

    result = ranked_query.all()

    # Extract session IDs and ranks
    session_ids_with_ranks = {row.chat_session_id: row.rank for row in result}
    session_ids = list(session_ids_with_ranks.keys())

    if not session_ids:
        return [], False

    # Now, let's query the actual ChatSession objects using the IDs
    stmt = select(ChatSession).where(ChatSession.id.in_(session_ids))

    if user_id:
        stmt = stmt.where(ChatSession.user_id == user_id)
    if not include_onyxbot_flows:
        stmt = stmt.where(ChatSession.onyxbot_flow.is_(False))
    if not include_deleted:
        stmt = stmt.where(ChatSession.deleted.is_(False))

    # Full objects with eager loading
    result = db_session.execute(stmt.options(joinedload(ChatSession.persona)))
    chat_sessions = result.scalars().all()

    # Sort based on above ranking
    chat_sessions = sorted(
        chat_sessions,
        key=lambda session: (
            -session_ids_with_ranks.get(session.id, 0),  # Rank (higher first)
            session.time_created.timestamp() * -1,  # Then by time (newest first)
        ),
    )

    has_more = len(chat_sessions) > page_size
    if has_more:
        chat_sessions = chat_sessions[:page_size]

    return chat_sessions, has_more
