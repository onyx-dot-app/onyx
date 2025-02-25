from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import ChatSession


def search_chat_sessions(
    user_id: UUID,
    db_session: Session,
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    include_deleted: bool = False,
    include_onyxbot_flows: bool = False,
) -> Tuple[List[ChatSession], bool, Optional[Dict[UUID, List[str]]]]:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.

    Returns a tuple of (chat_sessions, has_more)
    """
    # Base query for chat sessions
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)

    if not include_onyxbot_flows:
        stmt = stmt.where(ChatSession.onyxbot_flow.is_(False))

    if not include_deleted:
        stmt = stmt.where(ChatSession.deleted.is_(False))

    # If a search query is provided, filter by description or message content
    if query and query.strip():
        # For description search, we can still use LIKE for simplicity
        query_lower = f"%{query.lower()}%"
        description_matches = select(ChatSession.id).where(
            ChatSession.user_id == user_id,
            func.lower(ChatSession.description).like(query_lower),
        )

        # Debug: Count description matches
        description_match_count = db_session.execute(
            select(func.count()).select_from(description_matches.subquery())
        ).scalar_one()
        print(f"Description matches count: {description_match_count}")

        # For message content search, first try PostgreSQL's full-text search
        search_terms = query.strip()
        if len(search_terms.split()) > 1:
            search_terms = " & ".join(search_terms.split())

        # Try full-text search first with both English and simple dictionaries
        # This approach works better with short words and partial matches
        ranked_messages_sql = text(
            """
            SELECT
                chat_session_id,
                ts_rank(message_tsv, to_tsquery('english', :english_query)) +
                ts_rank(message_tsv, to_tsquery('simple', :simple_query)) AS search_rank
            FROM chat_message
            WHERE message_type = :message_type
            AND (
                message_tsv @@ to_tsquery('english', :english_query)
                OR message_tsv @@ to_tsquery('simple', :simple_query)
            )
            """
        ).bindparams(
            english_query=f"{search_terms}:*",  # Add prefix matching
            simple_query=f"{search_terms}:*",  # Add prefix matching
            message_type=MessageType.USER.value,
        )

        ranked_messages = db_session.execute(ranked_messages_sql).all()

        if len(ranked_messages) == 0:
            direct_match_sql = text(
                """
                SELECT
                    chat_session_id,
                    0.25 AS search_rank
                FROM chat_message
                WHERE message ILIKE :simple_query
                """
            ).bindparams(simple_query=f"%{query}%")

            ranked_messages = db_session.execute(direct_match_sql).all()

        # Extract chat session IDs with their ranks
        chat_session_ranks = {}
        for row in ranked_messages:
            chat_id = row.chat_session_id
            rank = row.search_rank
            if chat_id in chat_session_ranks:
                chat_session_ranks[chat_id] = max(chat_session_ranks[chat_id], rank)
            else:
                chat_session_ranks[chat_id] = rank

        # Get chat session IDs from message matches
        message_match_ids = list(chat_session_ranks.keys())

        # Combine the two queries
        stmt = stmt.where(
            or_(
                ChatSession.id.in_(description_matches),
                ChatSession.id.in_(message_match_ids),
            )
        )

        # If we have message matches with ranking, order by rank first, then by time
        if query.strip() and message_match_ids:
            # Get all matching chat sessions
            chat_sessions = (
                db_session.execute(stmt.options(joinedload(ChatSession.persona)))
                .scalars()
                .all()
            )

            # Sort chat sessions by rank (if available) and then by time_created
            chat_sessions = sorted(
                chat_sessions,
                key=lambda session: (
                    -chat_session_ranks.get(
                        session.id, 0
                    ),  # Negative for descending rank
                    session.time_created.timestamp()
                    * -1,  # Negative for descending time
                ),
            )

            # Apply pagination manually
            len(chat_sessions)
            offset = (page - 1) * page_size
            end_idx = offset + page_size + 1  # Get one extra to check if there are more

            paginated_sessions = chat_sessions[offset:end_idx]

            # Check if there are more results
            has_more = len(paginated_sessions) > page_size
            if has_more:
                paginated_sessions = paginated_sessions[:page_size]

            return paginated_sessions, has_more
        else:
            # If no specific search or no message matches, just order by time
            stmt = stmt.order_by(desc(ChatSession.time_created))
    else:
        # If no search query, just order by most recent first
        stmt = stmt.order_by(desc(ChatSession.time_created))

    # Get total count for pagination
    db_session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(
        page_size + 1
    )  # Get one extra to check if there are more

    # Execute query with eager loading of related data
    result = db_session.execute(stmt.options(joinedload(ChatSession.persona)))

    chat_sessions = result.scalars().all()

    # Check if there are more results
    has_more = len(chat_sessions) > page_size
    if has_more:
        chat_sessions = chat_sessions[:page_size]

    return chat_sessions, has_more
