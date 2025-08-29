from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type


class UserFileSnapshot(BaseModel):
    id: UUID
    name: str
    project_id: int | None = None
    user_id: UUID | None
    file_id: str
    created_at: datetime
    status: UserFileStatus
    last_accessed_at: datetime
    file_type: str
    chat_file_type: ChatFileType

    @classmethod
    def from_model(cls, model: UserFile) -> "UserFileSnapshot":
        return cls(
            id=model.id,
            name=model.name,
            project_id=model.folder_id,
            user_id=model.user_id,
            file_id=model.file_id,
            created_at=model.created_at,
            status=model.status,
            last_accessed_at=model.last_accessed_at,
            file_type=model.content_type,
            chat_file_type=mime_type_to_chat_file_type(model.content_type),
        )


class UserProjectSnapshot(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    user_id: UUID

    @classmethod
    def from_model(cls, model: UserFolder) -> "UserProjectSnapshot":
        return cls(
            id=model.id,
            name=model.name,
            description=model.description,
            created_at=model.created_at,
            user_id=model.user_id,
        )
