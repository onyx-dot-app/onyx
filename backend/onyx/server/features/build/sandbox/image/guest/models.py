"""Filesystem metadata shared by the guest command and API server."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from . import MAX_HISTORY_ARCHIVE_BYTES as MAX_HISTORY_ARCHIVE_BYTES

_HIDDEN_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
        "opencode.json",
        "nextjs.log",
        "nextjs.pid",
    }
)


def is_hidden_workspace_name(name: str) -> bool:
    return name.startswith(".") or name in _HIDDEN_NAMES


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionRequest(EmptyRequest):
    session_id: UUID


class PathRequest(SessionRequest):
    path: str = ""


class UploadRequest(SessionRequest):
    filename: str


class WriteRequest(EmptyRequest):
    path: str
    session_id: UUID | None = None


class RunRequest(EmptyRequest):
    argv: list[str] = Field(min_length=1)
    cwd: str = "/workspace"
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    has_stdin: bool = False


class ManagedRequest(EmptyRequest):
    mount_path: str


class FilesystemEntry(BaseModel):
    """A workspace file or directory, shared by the guest and API server."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    is_directory: bool
    size: int | None = None
    mime_type: str | None = None


class FilesystemListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[FilesystemEntry]


class OutputsManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size: int
    mtime_ns: int
    ctime_ns: int = 0


class OutputsManifestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[OutputsManifestEntry]
    complete: bool = True
