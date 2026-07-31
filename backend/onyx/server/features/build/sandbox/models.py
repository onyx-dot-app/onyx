"""Pydantic models for sandbox module communication."""

from datetime import datetime
from enum import Enum
from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


class ImageMoveOutcome(str, Enum):
    """How far a backend got moving a sandbox onto a new image."""

    MOVED = "moved"
    # Runtime discarded, workspace kept; only the caller can provision.
    NEEDS_PROVISION = "needs_provision"
    # The move was applied but the sandbox did not come back on it. Nothing to
    # fall back to: the old runtime is already gone, so a caller must leave the
    # sandbox alone rather than reach for a path that assumes a healthy pod.
    DISRUPTED = "disrupted"
    # Nothing was touched; the sandbox is exactly as it was.
    UNSUPPORTED = "unsupported"


class SandboxImageTarget(BaseModel):
    """The image sandboxes should run, confirmed present where they run.

    ``ref`` must be digest-pinned: patching a tag onto a pod already running
    that tag is not a change, so a swap would silently do nothing.
    """

    model_config = ConfigDict(frozen=True)

    ref: str
    digest: str


class SandboxImageState(BaseModel):
    """What sandboxes should run and what they are running, as one snapshot.

    ``target`` is None when the backend cannot confirm an image is both current
    and present where sandboxes run; that means "don't act", never "nothing to
    do".

    ``movable_digests`` covers only sandboxes that could be moved onto the target
    right now: their host is confirmed to hold it, and their runtime has reported
    what they run. A sandbox on a host that cannot be vouched for is absent
    rather than guessed at, because moving one onto an image its host lacks takes
    it down until the pull finishes.
    """

    model_config = ConfigDict(frozen=True)

    target: SandboxImageTarget | None
    movable_digests: dict[UUID, str]

    def stale_sandbox_ids(self) -> set[UUID]:
        """Sandboxes running something other than the target, if one is known."""
        if self.target is None:
            return set()
        return {
            sandbox_id
            for sandbox_id, digest in self.movable_digests.items()
            if digest != self.target.digest
        }


def sandbox_image_digest(image: str | None) -> str | None:
    """The digest of an image reference, with or without a repository prefix."""
    return image.rpartition("@")[-1] if image else None


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


class SandboxProvisionContentionError(Exception):
    """Another provisioner holds this sandbox's provisioning lock. Retryable:
    the lifecycle layer records the attempt FAILED and the caller re-reserves."""
