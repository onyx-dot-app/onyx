from datetime import datetime
from datetime import timedelta
from typing import List
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.chat_search import search_chat_sessions
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.server.query_and_chat.chat_search_models import ChatSearchResponse
from onyx.server.query_and_chat.chat_search_models import ChatSessionGroup
from onyx.server.query_and_chat.chat_search_models import ChatSessionSummary

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/search", response_model=ChatSearchResponse)
async def search_chats(
    query: Optional[str] = Query(None),
    page: int = Query(1),
    page_size: int = Query(10),
    include_highlights: bool = Query(True),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSearchResponse:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.

    Parameters:
    - query: Optional search query
    - page: Page number for pagination
    - page_size: Number of results per page
    - include_highlights: Whether to include highlighted snippets of matching text

    Returns:
    - Chat sessions grouped by time period
    - Whether there are more results
    - Next page number if there are more results
    - Highlighted snippets of matching text for each chat session
    """
    print("fetching with highlights", include_highlights)
    # Use the enhanced database function for chat search
    chat_sessions, has_more, highlights_by_session_id = search_chat_sessions(
        user_id=user.id if user else None,
        db_session=db_session,
        query=query,
        page=page,
        page_size=page_size,
        include_deleted=False,
        include_onyxbot_flows=False,
        include_highlights=include_highlights,
    )

    # Group chat sessions by time period
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    this_week = today - timedelta(days=7)
    this_month = today - timedelta(days=30)

    today_chats: List[ChatSessionSummary] = []
    yesterday_chats: List[ChatSessionSummary] = []
    this_week_chats: List[ChatSessionSummary] = []
    this_month_chats: List[ChatSessionSummary] = []
    older_chats: List[ChatSessionSummary] = []

    for session in chat_sessions:
        session_date = session.time_created.date()

        # Add highlights if available
        highlights = None
        if highlights_by_session_id and session.id in highlights_by_session_id:
            highlights = highlights_by_session_id[session.id]

        chat_summary = ChatSessionSummary(
            id=session.id,
            name=session.description,
            persona_id=session.persona_id,
            time_created=session.time_created,
            shared_status=session.shared_status,
            folder_id=session.folder_id,
            current_alternate_model=session.current_alternate_model,
            current_temperature_override=session.temperature_override,
            highlights=highlights,
        )

        if session_date == today:
            today_chats.append(chat_summary)
        elif session_date == yesterday:
            yesterday_chats.append(chat_summary)
        elif session_date > this_week:
            this_week_chats.append(chat_summary)
        elif session_date > this_month:
            this_month_chats.append(chat_summary)
        else:
            older_chats.append(chat_summary)

    # Create groups
    groups = []
    if today_chats:
        groups.append(ChatSessionGroup(title="Today", chats=today_chats))
    if yesterday_chats:
        groups.append(ChatSessionGroup(title="Yesterday", chats=yesterday_chats))
    if this_week_chats:
        groups.append(ChatSessionGroup(title="This Week", chats=this_week_chats))
    if this_month_chats:
        groups.append(ChatSessionGroup(title="This Month", chats=this_month_chats))
    if older_chats:
        groups.append(ChatSessionGroup(title="Older", chats=older_chats))

    return ChatSearchResponse(
        groups=groups,
        has_more=has_more,
        next_page=page + 1 if has_more else None,
    )
