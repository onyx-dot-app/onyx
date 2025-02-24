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


def get_search_highlights(
    chat_session_id: UUID,
    search_query: str,
    db_session: Session,
    max_highlights: int = 3,
) -> List[str]:
    """
    Get highlighted snippets of text that match the search query for a specific chat session.

    Args:
        chat_session_id: The UUID of the chat session
        search_query: The search query
        db_session: The database session
        max_highlights: Maximum number of highlights to return

    Returns:
        A list of highlighted text snippets
    """
    if not search_query or not search_query.strip():
        return []

    # Prepare the search query for ts_query
    search_terms = " & ".join(search_query.strip().split())

    # Use PostgreSQL's ts_headline to highlight matching terms
    # This will return snippets of text with the matching terms highlighted
    query = text(
        """
        SELECT ts_headline(
            'english',
            message,
            to_tsquery('english', :search_terms),
            'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=20, ShortWord=3, MaxFragments=1'
        ) as highlight
        FROM chat_message
        WHERE chat_session_id = :chat_session_id
        AND message_type = :message_type
        AND to_tsvector('english', message) @@ to_tsquery('english', :search_terms)
        ORDER BY ts_rank(to_tsvector('english', message), to_tsquery('english', :search_terms)) DESC
        LIMIT :max_highlights
    """
    )

    result = db_session.execute(
        query,
        {
            "search_terms": search_terms,
            "chat_session_id": chat_session_id,
            "message_type": MessageType.USER.value,
            "max_highlights": max_highlights,
        },
    )

    return [row.highlight for row in result]


def search_chat_sessions(
    user_id: UUID,
    db_session: Session,
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    include_deleted: bool = False,
    include_onyxbot_flows: bool = False,
    include_highlights: bool = True,
) -> Tuple[List[ChatSession], bool, Optional[Dict[UUID, List[str]]]]:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.

    Returns a tuple of (chat_sessions, has_more, highlights_by_session_id)
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

        # For message content search, use PostgreSQL's full-text search
        # First, prepare the search query by converting it to a tsquery format
        # Replace spaces with & for AND operations in the search
        search_terms = " & ".join(query.strip().split())

        # Create a direct SQL query for ranking messages
        # This approach avoids the issue with column access in subqueries
        ranked_messages_sql = text(
            """
            SELECT
                chat_session_id,
                ts_rank(to_tsvector('english', message), to_tsquery('english', :search_terms)) AS search_rank
            FROM chat_message
            WHERE message_type = :message_type
            AND to_tsvector('english', message) @@ to_tsquery('english', :search_terms)
        """
        ).bindparams(search_terms=search_terms, message_type=MessageType.USER.value)

        # Create a subquery from the SQL text
        ranked_messages = db_session.execute(ranked_messages_sql).all()

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

            # Get highlights if requested
            highlights_by_session_id = None
            if include_highlights and query and query.strip() and paginated_sessions:
                highlights_by_session_id = {}
                for session in paginated_sessions:
                    highlights = get_search_highlights(
                        chat_session_id=session.id,
                        search_query=query,
                        db_session=db_session,
                    )
                    if highlights:
                        highlights_by_session_id[session.id] = highlights

            return paginated_sessions, has_more, highlights_by_session_id
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

    # Get highlights for each chat session if requested and if there's a search query
    highlights_by_session_id = None
    if include_highlights and query and query.strip() and chat_sessions:
        highlights_by_session_id = {}
        for session in chat_sessions:
            highlights = get_search_highlights(
                chat_session_id=session.id, search_query=query, db_session=db_session
            )
            if highlights:
                highlights_by_session_id[session.id] = highlights

    return chat_sessions, has_more, highlights_by_session_id
