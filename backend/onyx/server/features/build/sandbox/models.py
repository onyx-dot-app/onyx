"""Pydantic models for sandbox module communication."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import SandboxStatus


class LLMProviderConfig(BaseModel):
    """LLM provider configuration for sandbox provisioning.

    Passed to SandboxManager.provision() to configure the LLM.
    """

    provider: str
    model_name: str
    api_key: str | None
    api_base: str | None


class SandboxInfo(BaseModel):
    """Information about a sandbox instance.

    Returned by SandboxManager.provision() and other methods.
    """

    sandbox_id: UUID
    directory_path: str
    status: SandboxStatus
    last_heartbeat: datetime | None


class SnapshotResult(BaseModel):
    """Result of creating a snapshot (without DB record).

    Returned by SandboxManager.create_snapshot().
    The caller is responsible for creating the DB record.
    """

    storage_path: str
    size_bytes: int


class SnapshotInfo(BaseModel):
    """Full information about a sandbox snapshot (including DB info).

    Used when returning snapshot information to API callers.
    """

    id: str
    sandbox_id: str
    storage_path: str
    created_at: datetime
    size_bytes: int


class FilesystemEntry(BaseModel):
    """Represents a file or directory entry in the sandbox filesystem.

    Used for directory listing operations. This is the canonical model used
    by both sandbox managers and the API layer.
    """

    name: str
    path: str
    is_directory: bool
    size: int | None = None  # File size in bytes (None for directories)
    mime_type: str | None = None  # MIME type (None for directories)
