import re
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


def update_message_tsv_column(db_session: Session) -> dict:
    """
    Manually update the message_tsv column for all chat messages.
    This can be used if the trigger isn't working or if the migration didn't properly populate the column.

    Returns:
        A dictionary with the results of the update operation.
    """
    try:
        # Count total messages
        total_count_query = text("SELECT COUNT(*) FROM chat_message")
        total_count = db_session.execute(total_count_query).scalar_one()

        # Count messages with NULL message_tsv
        null_count_query = text(
            "SELECT COUNT(*) FROM chat_message WHERE message_tsv IS NULL"
        )
        null_count_before = db_session.execute(null_count_query).scalar_one()

        # Update all messages using the improved approach with both English and simple dictionaries
        update_query = text(
            """
            UPDATE chat_message
            SET message_tsv =
                setweight(to_tsvector('english', message), 'A') ||
                setweight(to_tsvector('simple', message), 'B')
            WHERE message_tsv IS NULL OR
                  message_tsv != (
                      setweight(to_tsvector('english', message), 'A') ||
                      setweight(to_tsvector('simple', message), 'B')
                  )
            """
        )
        db_session.execute(update_query)
        db_session.commit()

        # Count messages with NULL message_tsv after update
        null_count_after = db_session.execute(null_count_query).scalar_one()

        return {
            "total_messages": total_count,
            "null_before_update": null_count_before,
            "null_after_update": null_count_after,
            "updated_count": null_count_before - null_count_after,
        }
    except Exception as e:
        db_session.rollback()
        return {"error": str(e)}


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

    try:
        # Prepare the search query for ts_query
        # For single words, don't add operators
        search_terms = search_query.strip()
        if len(search_terms.split()) > 1:
            search_terms = " & ".join(search_terms.split())

        print(
            f"Executing highlight query for session {chat_session_id} with terms: '{search_terms}'"
        )

        # First try using PostgreSQL's ts_headline with full-text search
        # Use both English and simple dictionaries for better coverage
        query = text(
            """
            SELECT ts_headline(
                'english',
                message,
                to_tsquery('english', :english_query),
                'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=20, ShortWord=3, MaxFragments=1'
            ) as highlight
            FROM chat_message
            WHERE chat_session_id = :chat_session_id
            AND message_type = :message_type
            AND (
                message_tsv @@ to_tsquery('english', :english_query)
                OR message_tsv @@ to_tsquery('simple', :simple_query)
            )
            ORDER BY
                ts_rank(message_tsv, to_tsquery('english', :english_query)) +
                ts_rank(message_tsv, to_tsquery('simple', :simple_query)) DESC
            LIMIT :max_highlights
            """
        )

        result = db_session.execute(
            query,
            {
                "english_query": f"{search_terms}:*",  # Add prefix matching
                "simple_query": f"{search_terms}:*",  # Add prefix matching
                "chat_session_id": chat_session_id,
                "message_type": MessageType.USER.value,
                "max_highlights": max_highlights,
            },
        )

        highlights = [row.highlight for row in result]

        # If no highlights found with full-text search, try a fallback approach
        if not highlights:
            print(
                f"No highlights found with full-text search, trying fallback for session {chat_session_id}"
            )

            # Fallback to simple ILIKE search with manual highlighting
            fallback_query = text(
                """
                SELECT message
                FROM chat_message
                WHERE chat_session_id = :chat_session_id
                AND message_type = :message_type
                AND message ILIKE :simple_query
                LIMIT :max_highlights
                """
            )

            fallback_result = db_session.execute(
                fallback_query,
                {
                    "chat_session_id": chat_session_id,
                    "message_type": MessageType.USER.value,
                    "simple_query": f"%{search_query}%",
                    "max_highlights": max_highlights,
                },
            )

            # Manually create highlights by wrapping the search term in <mark> tags
            for row in fallback_result:
                message = row.message
                # Simple highlighting - not as sophisticated as ts_headline but works for basic cases
                # Case-insensitive replacement
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                highlighted = pattern.sub(r"<mark>\g<0></mark>", message)

                # Truncate to a reasonable length around the match
                match_pos = highlighted.lower().find("<mark>")
                if match_pos >= 0:
                    start_pos = max(0, match_pos - 50)
                    end_pos = min(len(highlighted), match_pos + 100)
                    if start_pos > 0:
                        highlighted = "..." + highlighted[start_pos:end_pos] + "..."
                    else:
                        highlighted = highlighted[:end_pos] + "..."

                highlights.append(highlighted)

            # If still no highlights, try a more direct approach
            if not highlights:
                print(
                    f"No highlights found with ILIKE, trying direct match for session {chat_session_id}"
                )

                # Try to find any message that contains the search term
                direct_query = text(
                    """
                    SELECT message
                    FROM chat_message
                    WHERE chat_session_id = :chat_session_id
                    AND message_type = :message_type
                    LIMIT :max_highlights
                    """
                )

                direct_result = db_session.execute(
                    direct_query,
                    {
                        "chat_session_id": chat_session_id,
                        "message_type": MessageType.USER.value,
                        "max_highlights": max_highlights,
                    },
                )

                for row in direct_result:
                    message = row.message
                    # Check if the message contains the search term (case-insensitive)
                    if search_query.lower() in message.lower():
                        # Simple highlighting
                        pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                        highlighted = pattern.sub(r"<mark>\g<0></mark>", message)

                        # Truncate to a reasonable length around the match
                        match_pos = highlighted.lower().find("<mark>")
                        if match_pos >= 0:
                            start_pos = max(0, match_pos - 50)
                            end_pos = min(len(highlighted), match_pos + 100)
                            if start_pos > 0:
                                highlighted = (
                                    "..." + highlighted[start_pos:end_pos] + "..."
                                )
                            else:
                                highlighted = highlighted[:end_pos] + "..."

                        highlights.append(highlighted)

        print(f"Found {len(highlights)} highlights for session {chat_session_id}")
        return highlights

    except Exception as e:
        print(f"Error getting search highlights: {str(e)}")
        return []


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

        # Debug: Count description matches
        description_match_count = db_session.execute(
            select(func.count()).select_from(description_matches.subquery())
        ).scalar_one()
        print(f"Description matches count: {description_match_count}")

        # For message content search, first try PostgreSQL's full-text search
        search_terms = query.strip()
        if len(search_terms.split()) > 1:
            search_terms = " & ".join(search_terms.split())

        print(f"Searching for messages with terms: '{search_terms}'")

        # Debug: Check if message_tsv column exists and has data
        check_tsv_column = text(
            """
            SELECT COUNT(*)
            FROM chat_message
            WHERE message_tsv IS NOT NULL
            """
        )
        tsv_count = db_session.execute(check_tsv_column).scalar_one()
        print(f"Number of messages with non-null message_tsv: {tsv_count}")

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
        print(f"Full-text search message matches count: {len(ranked_messages)}")

        # If full-text search doesn't find matches, try a more flexible approach
        # This is especially helpful for short words that might be stopwords or partial matches
        if len(ranked_messages) == 0:
            print("No full-text matches found, trying ILIKE search as fallback")
            fallback_sql = text(
                """
                SELECT
                    chat_session_id,
                    1.0 AS search_rank
                FROM chat_message
                WHERE message_type = :message_type
                AND message ILIKE :simple_query
                """
            ).bindparams(simple_query=f"%{query}%", message_type=MessageType.USER.value)

            ranked_messages = db_session.execute(fallback_sql).all()
            print(
                f"ILIKE fallback search message matches count: {len(ranked_messages)}"
            )

            # If still no matches, try a more aggressive approach for very short queries
            if len(ranked_messages) == 0 and len(query.strip()) <= 3:
                print("Trying more aggressive search for short query")
                # For very short queries, try to match individual words
                word_parts_sql = text(
                    """
                    SELECT
                        chat_session_id,
                        0.5 AS search_rank
                    FROM chat_message
                    WHERE message_type = :message_type
                    AND (
                        message ~* :word_boundary_query
                        OR message ILIKE :start_query
                    )
                    """
                ).bindparams(
                    word_boundary_query=f"\\b{query}\\b|\\b{query}[a-z]|[a-z]{query}\\b",
                    start_query=f"{query}%",
                    message_type=MessageType.USER.value,
                )

                ranked_messages = db_session.execute(word_parts_sql).all()
                print(
                    f"Aggressive search message matches count: {len(ranked_messages)}"
                )

        # If still no matches, use the direct query that found matches in the debug output
        if len(ranked_messages) == 0:
            print("No matches found with previous methods, trying direct content match")
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
            print(f"Direct match search found {len(ranked_messages)} matches")

        # Debug: If still no matches, show some sample messages
        if len(ranked_messages) == 0:
            debug_query = text(
                """
                SELECT id, message, message_tsv, chat_session_id
                FROM chat_message
                WHERE message ILIKE :simple_query
                LIMIT 5
                """
            ).bindparams(simple_query=f"%{query}%")

            debug_results = db_session.execute(debug_query).all()
            print(f"Debug query found {len(debug_results)} potential matches")

            # If debug query found matches but our search didn't, use these matches directly
            if debug_results:
                ranked_messages = [(row.chat_session_id, 0.1) for row in debug_results]
                print(f"Using {len(ranked_messages)} matches from debug query")

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

        print(f"Unique chat sessions with message matches: {len(message_match_ids)}")

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
                    print("getting search highlights for session", session.id)
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
