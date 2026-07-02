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


def install_lazy_content_loader(
    instance: BaseModel, loader: Callable[[], bytes]
) -> None:
    """Stash a lazy ``content`` loader + per-instance lock on a Pydantic model.

    Used by ``lazy_from_*`` classmethod factories on models whose
    ``content: bytes`` field should be populated on first read instead of at
    construction. Pair with ``maybe_materialize_lazy_content``, which the
    model's ``__getattribute__`` calls when ``content`` is accessed.

    Sidecar attrs are written via ``object.__setattr__`` so they live on the
    instance ``__dict__`` without becoming Pydantic fields — serialization
    (``model_dump``) and equality are unaffected.
    """
    object.__setattr__(instance, _LAZY_LOADER_ATTR, loader)
    object.__setattr__(instance, _LAZY_DONE_ATTR, False)
    object.__setattr__(instance, _LAZY_LOCK_ATTR, threading.Lock())


def maybe_materialize_lazy_content(instance: BaseModel) -> None:
    """If a lazy loader is stashed and bytes haven't been read yet, invoke
    the loader under a per-instance lock and write the bytes back through
    Pydantic so subsequent reads of ``.content`` are zero-overhead field
    accesses.

    Two threads racing on first access must not both call the loader (that
    would double-GET from S3), hence the per-instance ``threading.Lock``
    with a double-checked guard inside the critical section.
    """
    d = object.__getattribute__(instance, "__dict__")
    if d.get(_LAZY_LOADER_ATTR) is None or d.get(_LAZY_DONE_ATTR, False):
        return
    lock = d.get(_LAZY_LOCK_ATTR)
    if lock is not None:
        with lock:
            if not d.get(_LAZY_DONE_ATTR, False):
                data = d[_LAZY_LOADER_ATTR]()
                BaseModel.__setattr__(instance, "content", data)
                object.__setattr__(instance, _LAZY_DONE_ATTR, True)
    else:
        # Defensive: install_lazy_content_loader always provides a lock,
        # but if a future caller wires up a loader without one, still
        # memoize correctly.
        data = d[_LAZY_LOADER_ATTR]()
        BaseModel.__setattr__(instance, "content", data)
        object.__setattr__(instance, _LAZY_DONE_ATTR, True)


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
        install_lazy_content_loader(inst, loader)
        return inst

    def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
        if name == "content":
            maybe_materialize_lazy_content(self)
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
