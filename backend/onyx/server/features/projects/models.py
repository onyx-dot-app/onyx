from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.models import UserProject
from onyx.db.projects import CategorizedFilesResult
from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.server.query_and_chat.models import ChatSessionDetails


class UserFileSnapshot(BaseModel):
    id: UUID
    temp_id: str | None = None  # Client-side temporary ID for optimistic updates
    name: str
    project_id: int | None = None
    user_id: UUID | None
    file_id: str
    created_at: datetime
    status: UserFileStatus
    last_accessed_at: datetime | None
    file_type: str | None
    chat_file_type: ChatFileType
    token_count: int | None
    chunk_count: int | None

    @classmethod
    def from_model(
        cls, model: UserFile, temp_id_map: dict[str, str] = {}
    ) -> "UserFileSnapshot":
        return cls(
            id=model.id,
            temp_id=temp_id_map.get(str(model.id)),
            name=model.name,
            project_id=None,
            user_id=model.user_id,
            file_id=model.file_id,
            created_at=model.created_at,
            status=model.status,
            last_accessed_at=model.last_accessed_at,
            file_type=model.content_type,
            chat_file_type=mime_type_to_chat_file_type(model.content_type),
            token_count=model.token_count,
            chunk_count=model.chunk_count,
        )


class TokenCountResponse(BaseModel):
    total_tokens: int


class CategorizedFilesSnapshot(BaseModel):
    user_files: list[UserFileSnapshot]
    non_accepted_files: list[str]
    unsupported_files: list[str]

    @classmethod
    def from_result(cls, result: CategorizedFilesResult) -> "CategorizedFilesSnapshot":
        return cls(
            user_files=[
                UserFileSnapshot.from_model(user_file, temp_id_map=result.id_to_temp_id)
                for user_file in result.user_files
            ],
            non_accepted_files=result.non_accepted_files,
            unsupported_files=result.unsupported_files,
        )


class UserProjectSnapshot(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    user_id: UUID | None
    instructions: str | None = None
    chat_sessions: list[ChatSessionDetails]

    @classmethod
    def from_model(cls, model: UserProject) -> "UserProjectSnapshot":
        return cls(
            id=model.id,
            name=model.name,
            description=model.description,
            created_at=model.created_at,
            user_id=model.user_id,
            instructions=model.instructions,
            chat_sessions=[
                ChatSessionDetails.from_model(chat)
                for chat in model.chat_sessions
                if not chat.deleted
            ],
        )


class ChatSessionRequest(BaseModel):
    chat_session_id: str
