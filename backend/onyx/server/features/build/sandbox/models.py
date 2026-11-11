"""Pydantic models for sandbox module communication."""

from datetime import datetime
from enum import Enum
from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    FilesystemEntry,
)
from onyx.server.gateway.models import GatewayModelDescriptor

FileSet: TypeAlias = dict[str, bytes]


class SandboxResourceKind(str, Enum):
    POD = "pod"
    SERVICE = "service"
    SECRET = "secret"
    CONTAINER = "container"
    VOLUME = "volume"


class SandboxResource(BaseModel):
    """Observed resource identity. Never derive a deletion target from a UUID prefix."""

    model_config = ConfigDict(frozen=True)

    kind: SandboxResourceKind
    name: str
    instance_id: str
    sandbox_id: UUID
    tenant_id: str
    created_at: datetime
    provisioning_attempt_number: int | None = None
    legacy_ownership: bool = False


class PromptAttachment(BaseModel):
    """A session-relative file to include in an OpenCode prompt."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    mime_type: str


class CraftLLMProviderConfig(BaseModel):
    provider: str
    model_name: str
    api_key: str | None
    api_base: str | None
    display_name: str | None = None
    models: list[GatewayModelDescriptor] | None = None


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


class SandboxCleanupCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    provisioning_attempt_number: int
    storage_identity: str
    last_heartbeat: datetime | None


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


class SandboxProvisionContentionError(Exception):
    """Another provisioner holds this sandbox's provisioning lock. Retryable:
    the lifecycle layer records the attempt FAILED and the caller re-reserves."""


# Harness sandboxes (harness_base.HarnessSandbox).


class HarnessSandboxRef(BaseModel):
    """The sandbox of one user, seen from one chat session."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID
    session_id: UUID
    # Lower bound of the VM attempt (the Sandbox row's attempt number). The
    # running VM can have a higher attempt.
    attempt: int = Field(default=1, ge=1)


class ExecOutputDelta(BaseModel):
    """New output of a command (stdout and stderr in arrival order)."""

    model_config = ConfigDict(frozen=True)

    text: str


class ExecCommandResult(BaseModel):
    """The last event of `exec_command` and `write_stdin`."""

    model_config = ConfigDict(frozen=True)

    # Output of this call, cut to max_output_tokens (head and tail).
    output: str
    # Set while the command runs: pass it to write_stdin.
    exec_session_id: str | None
    # Set when the command exited. None while it runs, or when a signal,
    # an interrupt or its deadline ended it.
    exit_code: int | None
    # "exited", "signaled", "canceled" or "deadline_exceeded" after the end.
    completion: str | None
    wall_time_seconds: float
    # Estimated tokens of the output before the token cut.
    original_token_count: int
    # True when the byte or token cap removed output.
    truncated: bool

    @property
    def running(self) -> bool:
        return self.exec_session_id is not None


class SandboxFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Relative to the session directory, "/"-separated.
    path: str
    name: str
    is_directory: bool
    size: int
    modified_at: datetime | None


class SandboxFileListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[SandboxFile]
    truncated: bool


ExecEvent: TypeAlias = ExecOutputDelta | ExecCommandResult
