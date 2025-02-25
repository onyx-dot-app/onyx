from datetime import datetime
from typing import List
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import ChatSessionSharedStatus


class ChatSessionSummary(BaseModel):
    id: UUID
    name: Optional[str] = None
    persona_id: Optional[int] = None
    time_created: datetime
    shared_status: ChatSessionSharedStatus
    folder_id: Optional[int] = None
    current_alternate_model: Optional[str] = None
    current_temperature_override: Optional[float] = None


class ChatSessionGroup(BaseModel):
    title: str
    chats: List[ChatSessionSummary]


class ChatSearchResponse(BaseModel):
    groups: List[ChatSessionGroup]
    has_more: bool
    next_page: Optional[int] = None


class ChatSearchRequest(BaseModel):
    query: Optional[str] = None
    page: int = 1
    page_size: int = 10


class CreateChatResponse(BaseModel):
    chat_session_id: str
