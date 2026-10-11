"""HTTP models and route constants shared by the sandbox daemon and API server.

Both sides import these constants and request models to keep the sidecar wire
contract in sync. The daemon imports this as ``sandbox_daemon.models`` (the
Dockerfile copies ``sandbox_daemon/`` to ``/workspace/sandbox_daemon/``); the
api-server imports the full module path.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

SIDECAR_HEALTH_PATH = "/health"
SIDECAR_READY_PATH = "/ready"
SIDECAR_PUSH_PATH = "/push"
PUSH_DAEMON_PORT = 8731
SIDECAR_FILESYSTEM_LIST_PATH = "/filesystem/list"
SIDECAR_OUTPUTS_MANIFEST_PATH = "/filesystem/outputs-manifest"
SIDECAR_SNAPSHOT_CREATE_PATH = "/snapshot/create"
SIDECAR_SNAPSHOT_RESTORE_PREFIX = "/snapshot/restore"
SIDECAR_SNAPSHOT_RESTORE_ROUTE = f"{SIDECAR_SNAPSHOT_RESTORE_PREFIX}/{{session_id}}"
SIDECAR_OPENCODE_HISTORY_CREATE_PATH = "/opencode-history/create"
SIDECAR_OPENCODE_HISTORY_RESTORE_PATH = "/opencode-history/restore"
SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH = "/opencode-history/mark-restored"
SIDECAR_PUSH_PUBLIC_KEY_ENV_VAR = "ONYX_SANDBOX_PUSH_PUBLIC_KEY"


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


def sidecar_snapshot_restore_path(session_id: UUID | str) -> str:
    return f"{SIDECAR_SNAPSHOT_RESTORE_PREFIX}/{session_id}"


class SnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


# Restore has no response body. Failures raise, success is the 204.


class FilesystemListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    path: str = ""


class FilesystemEntry(BaseModel):
    """A workspace file or directory, shared by the daemon and API server."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    is_directory: bool
    size: int | None = None
    mime_type: str | None = None


class FilesystemListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[FilesystemEntry]


class OutputsManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


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
