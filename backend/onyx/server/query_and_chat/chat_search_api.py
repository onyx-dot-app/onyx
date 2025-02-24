from datetime import datetime
from datetime import timedelta
from typing import List
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.auth import get_current_user
from onyx.auth.schemas import User
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.models import ChatSession
from onyx.server.query_and_chat.chat_search_models import ChatSearchResponse
from onyx.server.query_and_chat.chat_search_models import ChatSessionGroup
from onyx.server.query_and_chat.chat_search_models import ChatSessionSummary
from onyx.server.utils import get_db

router = APIRouter()


def group_chat_sessions(chat_sessions: List[ChatSession]) -> List[ChatSessionGroup]:
    """Group chat sessions by time period."""
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)
    last_month = today - timedelta(days=30)

    today_chats = []
    yesterday_chats = []
    last_week_chats = []
    last_month_chats = []
    older_chats = []

    for session in chat_sessions:
        session_date = session.time_created.date()

        if session_date == today:
            today_chats.append(session)
        elif session_date == yesterday:
            yesterday_chats.append(session)
        elif session_date > last_week:
            last_week_chats.append(session)
        elif session_date > last_month:
            last_month_chats.append(session)
        else:
            older_chats.append(session)

    groups = []

    if today_chats:
        groups.append(
            ChatSessionGroup(
                title="Today",
                chats=[
                    ChatSessionSummary(
                        id=chat.id,
                        name=chat.description,
                        persona_id=chat.persona_id,
                        time_created=chat.time_created,
                        shared_status=chat.shared_status,
                        folder_id=chat.folder_id,
                        current_alternate_model=chat.current_alternate_model,
                        current_temperature_override=chat.temperature_override,
                    )
                    for chat in today_chats
                ],
            )
        )

    if yesterday_chats:
        groups.append(
            ChatSessionGroup(
                title="Yesterday",
                chats=[
                    ChatSessionSummary(
                        id=chat.id,
                        name=chat.description,
                        persona_id=chat.persona_id,
                        time_created=chat.time_created,
                        shared_status=chat.shared_status,
                        folder_id=chat.folder_id,
                        current_alternate_model=chat.current_alternate_model,
                        current_temperature_override=chat.temperature_override,
                    )
                    for chat in yesterday_chats
                ],
            )
        )

    if last_week_chats:
        groups.append(
            ChatSessionGroup(
                title="Previous 7 Days",
                chats=[
                    ChatSessionSummary(
                        id=chat.id,
                        name=chat.description,
                        persona_id=chat.persona_id,
                        time_created=chat.time_created,
                        shared_status=chat.shared_status,
                        folder_id=chat.folder_id,
                        current_alternate_model=chat.current_alternate_model,
                        current_temperature_override=chat.temperature_override,
                    )
                    for chat in last_week_chats
                ],
            )
        )

    if last_month_chats:
        groups.append(
            ChatSessionGroup(
                title="Previous 30 Days",
                chats=[
                    ChatSessionSummary(
                        id=chat.id,
                        name=chat.description,
                        persona_id=chat.persona_id,
                        time_created=chat.time_created,
                        shared_status=chat.shared_status,
                        folder_id=chat.folder_id,
                        current_alternate_model=chat.current_alternate_model,
                        current_temperature_override=chat.temperature_override,
                    )
                    for chat in last_month_chats
                ],
            )
        )

    if older_chats:
        groups.append(
            ChatSessionGroup(
                title="Older",
                chats=[
                    ChatSessionSummary(
                        id=chat.id,
                        name=chat.description,
                        persona_id=chat.persona_id,
                        time_created=chat.time_created,
                        shared_status=chat.shared_status,
                        folder_id=chat.folder_id,
                        current_alternate_model=chat.current_alternate_model,
                        current_temperature_override=chat.temperature_override,
                    )
                    for chat in older_chats
                ],
            )
        )

    return groups


def filter_chat_sessions(
    chat_sessions: List[ChatSession], query: Optional[str]
) -> List[ChatSession]:
    """Filter chat sessions by search query."""
    if not query:
        return chat_sessions

    query = query.lower()
    filtered_sessions = []

    for session in chat_sessions:
        # Search in description (name)
        if session.description and query in session.description.lower():
            filtered_sessions.append(session)
            continue

        # Could add more search criteria here, like searching in messages

    return filtered_sessions


@router.get("/chat/search", response_model=ChatSearchResponse)
async def search_chats(
    query: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search for chat sessions."""
    # Get all chat sessions for the user
    all_chat_sessions = get_chat_sessions_by_user(
        user_id=current_user.id, deleted=False, db_session=db
    )

    # Filter by search query
    filtered_sessions = filter_chat_sessions(all_chat_sessions, query)

    # Calculate pagination
    total_sessions = len(filtered_sessions)
    total_pages = (total_sessions + page_size - 1) // page_size

    # Paginate the results
    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, total_sessions)
    paginated_sessions = filtered_sessions[start_idx:end_idx]

    # Group the paginated sessions
    grouped_sessions = group_chat_sessions(paginated_sessions)

    return ChatSearchResponse(
        groups=grouped_sessions,
        has_more=page < total_pages,
        next_page=page + 1 if page < total_pages else None,
    )
