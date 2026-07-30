"""Pydantic models for sandbox module communication."""

from datetime import datetime
from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from onyx.db.enums import SandboxStatus
from onyx.server.gateway.models import GatewayModelDescriptor

FileSet: TypeAlias = dict[str, bytes]


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


class SandboxImageIdentity(BaseModel):
    """What a live sandbox is running vs what the deployment wants now.

    Sandbox pods/containers are created imperatively and owned by no
    controller, so nothing reconciles a live one toward a new deployed image.
    This is the comparison that says whether it needs recycling.

    Both sides always come from the same manager: K8s compares registry
    manifest digests, Docker local image IDs, and the two are not
    interchangeable.
    """

    model_config = ConfigDict(frozen=True)

    # None when the sandbox is gone or its runtime hasn't reported yet.
    running_ref: str | None
    running_digest: str | None
    desired_ref: str
    desired_digest: str | None

    @field_validator("running_digest", "desired_digest")
    @classmethod
    def _strip_repository(cls, value: str | None) -> str | None:
        """Keep only the `sha256:...` part: a K8s imageID may or may not carry
        a repository prefix (`docker.io/onyxdotapp/sandbox@sha256:...`)
        depending on the runtime, while Docker image IDs never do."""
        if value is None:
            return None
        _, prefixed, digest = value.rpartition("@")
        return digest if prefixed else value

    @property
    def digest_comparable(self) -> bool:
        """Whether both sides resolved to a digest. False means the check has
        degraded to comparing refs, which cannot see a mutable tag being
        repointed at new content."""
        return self.running_digest is not None and self.desired_digest is not None

    @property
    def is_stale(self) -> bool:
        """Whether the sandbox is running something other than what a fresh
        one would be. Unknown identity is never stale — recycling costs a
        user their pod, so it takes positive evidence."""
        if self.digest_comparable:
            return self.running_digest != self.desired_digest
        if self.running_ref is None:
            return False
        return self.running_ref != self.desired_ref


class SandboxRuntimeState(BaseModel):
    """Liveness plus image identity of a sandbox, read together.

    One object because both come from the same backend read: splitting them
    would double the API calls on the provisioning hot path.
    """

    healthy: bool
    # None when the backend can't report image identity, or the sandbox is
    # gone. Callers must read it as "unknown", never as "current".
    image: SandboxImageIdentity | None = None


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
