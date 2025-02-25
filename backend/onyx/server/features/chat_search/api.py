from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Path
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.chat import create_chat_session
from onyx.db.chat import delete_chat_session
from onyx.db.chat_search import search_chat_sessions
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.db.persona import get_best_persona_id_for_user
from onyx.server.query_and_chat.chat_search_models import ChatSearchResponse
from onyx.server.query_and_chat.chat_search_models import ChatSessionGroup
from onyx.server.query_and_chat.chat_search_models import ChatSessionSummary
from onyx.server.query_and_chat.chat_search_models import CreateChatResponse

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


@router.post("/sessions", response_model=CreateChatResponse)
async def create_chat(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreateChatResponse:
    """
    Create a new chat session for the user.
    """
    user_id = user.id if user else None
    # Get the best persona ID for the user (default or specified)
    persona_id = get_best_persona_id_for_user(
        db_session=db_session,
        user=user,
        persona_id=None,  # Use default
    )

    # Create a new chat session
    chat_session = create_chat_session(
        db_session=db_session,
        description="",  # Empty description for new chat
        user_id=user_id,
        persona_id=persona_id,
        onyxbot_flow=False,
    )

    return CreateChatResponse(chat_session_id=str(chat_session.id))


@router.delete("/sessions/{chat_session_id}", response_model=Dict[str, bool])
async def delete_chat(
    chat_session_id: UUID = Path(
        ..., description="The ID of the chat session to delete"
    ),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Dict[str, bool]:
    """
    Delete a chat session.
    """
    user_id = user.id if user else None
    try:
        delete_chat_session(
            user_id=user_id,
            chat_session_id=chat_session_id,
            db_session=db_session,
        )
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat: {str(e)}")
