from typing import Optional
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.chat import create_chat_session
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.chat import update_chat_session
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse

router = APIRouter(prefix="/threads")


# Models
class Thread(BaseModel):
    id: UUID
    object: str = "thread"
    created_at: int
    metadata: Optional[dict[str, str]] = None


class CreateThreadRequest(BaseModel):
    messages: Optional[list[dict]] = None
    metadata: Optional[dict[str, str]] = None


class ModifyThreadRequest(BaseModel):
    metadata: Optional[dict[str, str]] = None


# API Endpoints
@router.post("")
def create_thread(
    request: CreateThreadRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Thread:
    user_id = user.id if user else None
    new_chat_session = create_chat_session(
        db_session=db_session,
        description="",  # Leave the naming till later to prevent delay
        user_id=user_id,
        persona_id=0,
    )

    return Thread(
        id=new_chat_session.id,
        created_at=int(new_chat_session.time_created.timestamp()),
        metadata=request.metadata,
    )


@router.get("/{thread_id}")
def retrieve_thread(
    thread_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Thread:
    user_id = user.id if user else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=thread_id,
            user_id=user_id,
            db_session=db_session,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")

    return Thread(
        id=chat_session.id,
        created_at=int(chat_session.time_created.timestamp()),
        metadata=None,  # Assuming we don't store metadata in our current implementation
    )


@router.post("/{thread_id}")
def modify_thread(
    thread_id: UUID,
    request: ModifyThreadRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Thread:
    user_id = user.id if user else None
    try:
        chat_session = update_chat_session(
            db_session=db_session,
            user_id=user_id,
            chat_session_id=thread_id,
            description=None,  # Not updating description
            sharing_status=None,  # Not updating sharing status
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")

    return Thread(
        id=chat_session.id,
        created_at=int(chat_session.time_created.timestamp()),
        metadata=request.metadata,
    )


@router.delete("/{thread_id}")
def delete_thread(
    thread_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict:
    user_id = user.id if user else None
    try:
        delete_chat_session(
            user_id=user_id,
            chat_session_id=thread_id,
            db_session=db_session,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")

    return {"id": str(thread_id), "object": "thread.deleted", "deleted": True}


@router.get("")
def list_threads(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    user_id = user.id if user else None
    chat_sessions = get_chat_sessions_by_user(
        user_id=user_id,
        deleted=False,
        db_session=db_session,
    )

    return ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=chat.id,
                name=chat.description,
                persona_id=chat.persona_id,
                time_created=chat.time_created.isoformat(),
                time_updated=chat.time_updated.isoformat(),
                shared_status=chat.shared_status,
                current_alternate_model=chat.current_alternate_model,
                current_temperature_override=chat.temperature_override,
            )
            for chat in chat_sessions
        ]
    )
