from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel

from onyx.db.models import UserFile
from onyx.db.models import UserFolder


class UserFileSnapshot(BaseModel):
    id: int
    name: str
    document_id: str
    folder_id: int | None = None
    user_id: UUID | None
    file_id: str
    created_at: datetime
    assistant_ids: List[int] = []  # List of assistant IDs
    token_count: int | None
    indexed: bool
    link_url: str | None
    failed: bool | None

    @classmethod
    def from_model(cls, model: UserFile) -> "UserFileSnapshot":
        return cls(
            id=model.id,
            name=model.name,
            folder_id=model.folder_id,
            document_id=model.document_id,
            user_id=model.user_id,
            file_id=model.file_id,
            created_at=model.created_at,
            assistant_ids=[assistant.id for assistant in model.assistants],
            token_count=model.token_count,
            failed=len(model.cc_pair.index_attempts) > 0
            and model.cc_pair.last_successful_index_time is None,
            indexed=model.cc_pair.last_successful_index_time is not None
            if model.cc_pair
            else False,
            link_url=model.link_url,
        )


class UserFolderSnapshot(BaseModel):
    id: int
    name: str
    description: str
    files: List[UserFileSnapshot]
    created_at: datetime
    user_id: UUID | None
    assistant_ids: List[int] = []  # List of assistant IDs
    token_count: int | None

    @classmethod
    def from_model(cls, model: UserFolder) -> "UserFolderSnapshot":
        return cls(
            id=model.id,
            name=model.name,
            description=model.description,
            files=[UserFileSnapshot.from_model(file) for file in model.files],
            created_at=model.created_at,
            user_id=model.user_id,
            assistant_ids=[assistant.id for assistant in model.assistants],
            token_count=sum(file.token_count or 0 for file in model.files) or None,
        )


class MessageResponse(BaseModel):
    message: str


class FileSystemResponse(BaseModel):
    folders: list[UserFolderSnapshot]
    files: list[UserFileSnapshot]
