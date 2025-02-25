from typing import List
from typing import Optional
from typing import Tuple
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

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

    # If no search query, use standard SQLAlchemy pagination
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

    # For search queries, use a two-step approach:
    # 1. Find matching IDs with ranking
    # 2. Query full objects with those IDs
    words = query.lower().strip().split()
    params = {}

    for i, word in enumerate(words):
        params[f"word_{i}"] = f"%{word}%"

    # SQL to get matching IDs with ranking
    message_conditions = " OR ".join(
        [f"LOWER(message) LIKE :word_{i}" for i in range(len(words))]
    )

    sql = f"""
    WITH message_matches AS (
        SELECT
            chat_session_id,
            1.0 AS search_rank
        FROM chat_message
        WHERE ({message_conditions})
        {"AND chat_message.user_id = :user_id" if user_id else ""}
    ),
    description_matches AS (
        SELECT
            id AS chat_session_id,
            0.5 AS search_rank
        FROM chat_session
        WHERE LOWER(description) LIKE :query_text
        {"AND user_id = :user_id" if user_id else ""}
        {"AND onyxbot_flow = FALSE" if not include_onyxbot_flows else ""}
        {"AND deleted = FALSE" if not include_deleted else ""}
    ),
    combined_matches AS (
        SELECT chat_session_id, MAX(search_rank) AS rank
        FROM (
            SELECT * FROM message_matches
            UNION ALL
            SELECT * FROM description_matches
        ) AS matches
        GROUP BY chat_session_id
    ),
    ranked_ids AS (
        SELECT
            chat_session_id,
            rank,
            ROW_NUMBER() OVER (ORDER BY rank DESC, chat_session_id) AS row_num
        FROM combined_matches
    )
    SELECT chat_session_id, rank
    FROM ranked_ids
    WHERE row_num > :offset AND row_num <= :limit
    """

    # Add query text to params
    params["query_text"] = f"%{query.lower()}%"
    if user_id:
        params["user_id"] = user_id
    params["offset"] = offset
    params["limit"] = offset + page_size + 1  # +1 to check if there are more

    # Execute the query to get IDs and ranks
    result = db_session.execute(text(sql).bindparams(**params))

    # Extract session IDs and ranks
    session_ids_with_ranks = {row.chat_session_id: row.rank for row in result}
    session_ids = list(session_ids_with_ranks.keys())

    if not session_ids:
        return [], False

    # Now query the actual ChatSession objects using the IDs
    stmt = select(ChatSession).where(ChatSession.id.in_(session_ids))

    if user_id:
        stmt = stmt.where(ChatSession.user_id == user_id)
    if not include_onyxbot_flows:
        stmt = stmt.where(ChatSession.onyxbot_flow.is_(False))
    if not include_deleted:
        stmt = stmt.where(ChatSession.deleted.is_(False))

    # Get the full objects with eager loading
    result = db_session.execute(stmt.options(joinedload(ChatSession.persona)))
    chat_sessions = result.scalars().all()

    # Sort according to our ranking
    chat_sessions = sorted(
        chat_sessions,
        key=lambda session: (
            -session_ids_with_ranks.get(session.id, 0),  # Rank (higher first)
            session.time_created.timestamp() * -1,  # Then by time (newest first)
        ),
    )

    # Check if there are more results
    has_more = len(chat_sessions) > page_size
    if has_more:
        chat_sessions = chat_sessions[:page_size]

    return chat_sessions, has_more
