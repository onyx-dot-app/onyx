"""Pydantic models for sandbox module communication."""

from datetime import datetime
from enum import Enum
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    FilesystemEntry,
)
from onyx.server.gateway.models import GatewayModelDescriptor

FileSet: TypeAlias = dict[str, bytes]

# Parent of each chat session's working directory in the sandbox.
SESSION_WORKSPACE_ROOT = "/home/onyx/workspaces"


def session_workspace(session_id: UUID) -> str:
    return f"{SESSION_WORKSPACE_ROOT}/{session_id}"


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
    """An MCP integration resolved for opencode `mcp` emission (URL only; the
    proxy injects credentials). ``key`` is the opencode server id.

    ``integration_id`` is not emitted into ``opencode.json``; it feeds the
    per-session runtime hash so a hot reload fires when the server set or tools
    change."""

    key: str
    url: str
    disabled_tools: tuple[str, ...] = ()
    integration_id: int


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


SandboxFileType = Literal["file", "directory", "other"]


# Why a path names nothing, other than a missing file.
SandboxPathFault = Literal["escapes", "loop", "other"]


class SandboxPathInfo(BaseModel):
    """What the guest kernel reports for a session path: the entry itself,
    and what it names through the links inside the session directory."""

    model_config = ConfigDict(frozen=True)

    # The entry itself exists, a broken link included.
    exists: bool
    is_link: bool
    # A link's stored target, as text.
    link_target: str | None
    # What the path names through its links; None when it names nothing
    # (missing or a broken link) or with `error`.
    type: SandboxFileType | None
    # Permission bits (mode & 0o777) of what the path names.
    mode: int | None
    # Equal for two paths that name one file.
    identity: tuple[int, int] | None
    # Why the path names nothing, other than a missing file: a link leads
    # out of the session directory, the links loop, or another error.
    error: SandboxPathFault | None


class ExecOutputDelta(BaseModel):
    """New output of a command (stdout and stderr in arrival order)."""

    model_config = ConfigDict(frozen=True)

    text: str


# How a command ended.
ExecCompletionName = Literal["exited", "signaled", "canceled", "deadline_exceeded"]


class ExecCommandResult(BaseModel):
    """The last event of `exec_command` and `write_stdin`."""

    model_config = ConfigDict(frozen=True)

    # The output of this call that the byte cap kept: the first and the last
    # half of EXEC_CALL_OUTPUT_MAX_BYTES, in arrival order, with
    # `omitted_chars` characters dropped between them.
    head: str
    tail: str
    omitted_chars: int
    # Set while the command runs: pass it to write_stdin.
    session_id: str | None
    # Set when the command exited. None while it runs, or when a signal,
    # an interrupt or its deadline ended it.
    exit_code: int | None
    # Set after the end. None while the command runs, or when the daemon
    # reported no kind of end.
    completion: ExecCompletionName | None
    wall_time_seconds: float
    # True when the byte cap dropped output, or the daemon lost some; a
    # reader's own cut does not count.
    truncated: bool

    @property
    def running(self) -> bool:
        return self.session_id is not None


ExecEvent: TypeAlias = ExecOutputDelta | ExecCommandResult
