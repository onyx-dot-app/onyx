import base64
from enum import Enum
from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel


class ChatFileType(str, Enum):
    IMAGE = "image"


class FileDescriptor(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    id: str
    type: ChatFileType


class InMemoryChatFile(BaseModel):
    file_id: UUID
    content: bytes
    file_type: ChatFileType = ChatFileType.IMAGE

    def to_base64(self) -> str:
        return base64.b64encode(self.content).decode()

    def to_file_descriptor(self) -> FileDescriptor:
        return {
            "id": str(self.file_id),
            "type": self.file_type,
        }
