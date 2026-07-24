"""Pydantic models for sandbox module communication."""

from datetime import datetime
from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import SandboxStatus

FileSet: TypeAlias = dict[str, bytes]


class GatewayModelConfig(BaseModel):
    id: str
    display_name: str
    supports_reasoning: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


class LLMProviderConfig(BaseModel):
    provider: str
    model_name: str
    api_key: str | None
    api_base: str | None
    npm_package: str | None = None
    display_name: str | None = None
    models: list[GatewayModelConfig] | None = None


class CraftMCPServerConfig(BaseModel):
    """A craft-enabled MCP server resolved for opencode `mcp` emission (URL only;
    the proxy injects credentials). ``key`` is the opencode server id.

    ``server_id`` is not emitted into ``opencode.json``; it feeds the per-session
    runtime hash so a hot reload fires when the server set or tools change."""

    key: str
    url: str
    disabled_tools: tuple[str, ...] = ()
    server_id: int


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


class DirectoryListing(BaseModel):
    path: str  # Current directory path
    entries: list[FilesystemEntry]  # Contents


class PushFailure(BaseModel):
    sandbox_id: UUID
    reason: str
    detail: str | None = None


class PushResult(BaseModel):
    targets: int
    succeeded: int
    failures: list[PushFailure]


class RetriableWriteError(Exception):
    """Transient failure in write_files_to_sandbox (timeout, pod not-ready)."""


class FatalWriteError(Exception):
    """Permanent failure in write_files_to_sandbox (validation, auth)."""
