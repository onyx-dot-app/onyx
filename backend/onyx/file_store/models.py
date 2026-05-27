import base64
import threading
from enum import Enum
from typing import Callable
from typing import NotRequired

from pydantic import BaseModel
from typing_extensions import TypedDict  # noreorder

# Sidecar attribute names used by the lazy-content materialization shim. They
# live on the instance via object.__setattr__ rather than as Pydantic fields,
# so they don't affect serialization, validation, or model_dump output.
_LAZY_LOADER_ATTR = "_lazy_content_loader"
_LAZY_DONE_ATTR = "_lazy_content_materialized"
_LAZY_LOCK_ATTR = "_lazy_content_lock"


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

    @classmethod
    def lazy_from_descriptor(
        cls,
        *,
        file_id: str,
        file_type: "ChatFileType",
        filename: str | None,
        loader: Callable[[], bytes],
    ) -> "InMemoryChatFile":
        """Construct an instance whose ``content`` bytes are loaded only on
        first access.

        Eager construction (``InMemoryChatFile(file_id=..., content=...)``) is
        unchanged. Lazy instances start with ``content=b""`` and a stashed
        loader; the first read of ``.content`` invokes the loader and memoizes
        the result.
        """
        inst = cls(
            file_id=file_id,
            content=b"",
            file_type=file_type,
            filename=filename,
        )
        object.__setattr__(inst, _LAZY_LOADER_ATTR, loader)
        object.__setattr__(inst, _LAZY_DONE_ATTR, False)
        object.__setattr__(inst, _LAZY_LOCK_ATTR, threading.Lock())
        return inst

    def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
        if name == "content":
            d = object.__getattribute__(self, "__dict__")
            if d.get(_LAZY_LOADER_ATTR) is not None and not d.get(
                _LAZY_DONE_ATTR, False
            ):
                # Lock the check-and-set so two threads racing on the first
                # access don't both call the loader and double-GET from S3.
                # ChatFile lives on PythonToolOverrideKwargs which can be
                # accessed by worker threads, so this matters in practice.
                lock = d.get(_LAZY_LOCK_ATTR)
                if lock is not None:
                    with lock:
                        if not d.get(_LAZY_DONE_ATTR, False):
                            data = d[_LAZY_LOADER_ATTR]()
                            BaseModel.__setattr__(self, "content", data)
                            object.__setattr__(self, _LAZY_DONE_ATTR, True)
                else:
                    # No lock present (shouldn't happen via lazy_from_*),
                    # fall back to the un-locked path.
                    data = d[_LAZY_LOADER_ATTR]()
                    BaseModel.__setattr__(self, "content", data)
                    object.__setattr__(self, _LAZY_DONE_ATTR, True)
        return object.__getattribute__(self, name)

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
