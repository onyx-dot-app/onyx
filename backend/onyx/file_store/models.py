import base64
from enum import Enum
from typing import NotRequired

from pydantic import BaseModel
from typing_extensions import TypedDict  # noreorder


class ChatFileType(str, Enum):
    # Image types only contain the binary data
    IMAGE = "image"
    # Doc types are saved as both the binary, and the parsed text
    DOC = "document"
    # Plain text only contain the text
    PLAIN_TEXT = "plain_text"
    # Tabular data files (CSV, XLSX)
    TABULAR = "tabular"

    def is_text_file(self) -> bool:
        return self in (
            ChatFileType.PLAIN_TEXT,
            ChatFileType.DOC,
            ChatFileType.TABULAR,
        )

    def use_metadata_only(self) -> bool:
        """File types where we can ignore the file content
        and only use the metadata."""
        return self in (ChatFileType.TABULAR,)


class FileDescriptor(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    id: str
    type: ChatFileType
    name: NotRequired[str | None]
    user_file_id: NotRequired[str | None]


class InMemoryChatFile(BaseModel):
    file_id: str
    content: bytes
    file_type: ChatFileType
    filename: str | None = None

    def to_base64(self) -> str:
        if self.file_type == ChatFileType.IMAGE:
            return base64.b64encode(self.content).decode()
        else:
            raise RuntimeError(
                "Should not be trying to convert a non-image file to base64"
            )

    def to_file_descriptor(self) -> FileDescriptor:
        return {
            "id": str(self.file_id),
            "type": self.file_type,
            "name": self.filename,
            "user_file_id": str(self.file_id) if self.file_id else None,
        }
