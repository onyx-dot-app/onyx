import base64
import threading
from enum import Enum
from typing import Any, Callable, NotRequired, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict  # noreorder


class _LazyContent:
    """Own one loader and cache shared by copied file descriptors.

    Two threads racing on first access must not both call the loader: that
    would fetch the same bytes from object storage twice. The lock protects
    the shared cache, including reads through copies of the descriptor.
    """

    def __init__(self, loader: Callable[[], bytes]) -> None:
        self._loader = loader
        self._lock = threading.Lock()
        self._content: bytes | None = None

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        return self

    def read(self) -> bytes:
        with self._lock:
            if self._content is None:
                self._content = self._loader()
            return self._content


def install_lazy_content_loader(
    instance: BaseModel, loader: Callable[[], bytes]
) -> None:
    """Attach shared resource ownership outside serialized descriptor fields.

    The model's __getattribute__ calls maybe_materialize_lazy_content when
    content is accessed. object.__setattr__ stores the resource in __dict__
    without adding a Pydantic field, so model_dump does not include it.
    """
    object.__setattr__(instance, "_lazy_content", _LazyContent(loader))


def maybe_materialize_lazy_content(instance: BaseModel) -> None:
    """Read shared content without copying loaders, locks, or cached bytes."""
    fields = object.__getattribute__(instance, "__dict__")
    resource = fields.get("_lazy_content")
    if isinstance(resource, _LazyContent) and not fields.get(
        "_lazy_materialized", False
    ):
        BaseModel.__setattr__(instance, "content", resource.read())
        object.__setattr__(instance, "_lazy_materialized", True)


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
        return self == ChatFileType.TABULAR


class FileDescriptor(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    id: str
    type: ChatFileType
    name: NotRequired[str | None]
    user_file_id: NotRequired[str | None]


class UserFileMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    file_id: str
    name: str
    file_type: str
    token_count: int | None


class ChatFileInput(BaseModel):
    descriptor: FileDescriptor
    token_count: int
    content_pending: bool


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

    def __getattribute__(self, name: str):
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


class ChatLoadedFile(InMemoryChatFile):
    content_text: str | None
    token_count: int
    # True while the user-file worker is still processing the file — its
    # canonical plaintext (e.g. including image captions) doesn't exist yet.
    content_pending: bool = False

    @classmethod
    def lazy_loaded(
        cls,
        *,
        file_id: str,
        file_type: ChatFileType,
        filename: str | None,
        content_text: str | None,
        token_count: int,
        loader: Callable[[], bytes],
        content_pending: bool = False,
    ) -> "ChatLoadedFile":
        """Keep supplied text and token counts; load bytes on first content access."""
        inst = cls(
            file_id=file_id,
            content=b"",
            file_type=file_type,
            filename=filename,
            content_text=content_text,
            token_count=token_count,
            content_pending=content_pending,
        )
        install_lazy_content_loader(inst, loader)
        return inst


class ContextFileMetadata(BaseModel):
    """Metadata for a context-injected file to enable citation support."""

    file_id: str
    filename: str
    file_content: str


class FileToolMetadata(BaseModel):
    """Lightweight metadata for exposing files to the FileReaderTool.

    Used when files cannot be loaded directly into context (project too large
    or persona-attached user_files without direct-load path). The LLM receives
    a listing of these so it knows which files it can read via ``read_file``.
    """

    file_id: str
    filename: str
    approx_char_count: int

    # Whether the bytes are available to tools that receive files (PythonTool).
    # Summary-truncated attachments are listed for the LLM but never staged;
    # listing them must not promise Python access to bytes it does not have.
    staged_for_tools: bool = True


class ExtractedContextFiles(BaseModel):
    """Result of attempting to load user files (from a project or persona) into context."""

    file_texts: list[str]
    image_files: list[ChatLoadedFile]
    use_as_search_filter: bool
    total_token_count: int
    # Full text and titles used to construct citations for injected files.
    file_metadata: list[ContextFileMetadata]
    uncapped_token_count: int | None
    # File listings supplied to the model for retrieval through FileReaderTool.
    file_metadata_for_tool: list[FileToolMetadata] = []
