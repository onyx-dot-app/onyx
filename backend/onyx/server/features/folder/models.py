from uuid import UUID

from pydantic import BaseModel

from onyx.server.query_and_chat.models import ChatSessionDetails


class UserFolderSnapshot(BaseModel):
    folder_id: int
    folder_name: str | None
    display_priority: int
    chat_sessions: list[ChatSessionDetails]


class GetUserFoldersResponse(BaseModel):
    folders: list[UserFolderSnapshot]


class FolderCreationRequest(BaseModel):
    folder_name: str | None = None


class FolderUpdateRequest(BaseModel):
    folder_name: str | None = None


class FolderChatSessionRequest(BaseModel):
    chat_session_id: UUID


class DeleteFolderOptions(BaseModel):
    including_chats: bool = False
