"""Pydantic models for sandbox module communication."""

from datetime import datetime

from pydantic import BaseModel

from onyx.db.enums import SandboxStatus


class SandboxInfo(BaseModel):
    """Information about a sandbox instance.

    Returned by SandboxManager.provision() and other methods.
    """

    id: str
    session_id: str
    directory_path: str
    status: SandboxStatus
    created_at: datetime
    last_heartbeat: datetime | None


class SnapshotInfo(BaseModel):
    """Information about a sandbox snapshot.

    Returned by SandboxManager.create_snapshot().
    """

    id: str
    session_id: str
    storage_path: str
    created_at: datetime
    size_bytes: int


class FilesystemEntry(BaseModel):
    """Represents a file or directory entry in the sandbox filesystem.

    Used for directory listing operations.
    """

    name: str
    path: str
    is_directory: bool
    size_bytes: int | None
    modified_at: datetime | None
