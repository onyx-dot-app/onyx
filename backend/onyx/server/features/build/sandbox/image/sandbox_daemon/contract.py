"""HTTP contract shared between the sandbox daemon and the api-server.

Both sides import these constants and request models to keep the sidecar wire
contract in sync. The daemon imports this as ``sandbox_daemon.contract`` (the
Dockerfile copies ``sandbox_daemon/`` to ``/workspace/sandbox_daemon/``); the
api-server imports the full module path.
"""

from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict

SIDECAR_HEALTH_PATH = "/health"
SIDECAR_READY_PATH = "/ready"
SIDECAR_PUSH_PATH = "/push"
PUSH_DAEMON_PORT = 8731
SIDECAR_FILESYSTEM_LIST_PATH = "/filesystem/list"
SIDECAR_SNAPSHOT_CREATE_PATH = "/snapshot/create"
SIDECAR_SNAPSHOT_RESTORE_PREFIX = "/snapshot/restore"
SIDECAR_SNAPSHOT_RESTORE_ROUTE = f"{SIDECAR_SNAPSHOT_RESTORE_PREFIX}/{{session_id}}"
SIDECAR_OPENCODE_HISTORY_CREATE_PATH = "/opencode-history/create"
SIDECAR_OPENCODE_HISTORY_RESTORE_PATH = "/opencode-history/restore"
SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH = "/opencode-history/mark-restored"
SIDECAR_PUSH_PUBLIC_KEY_ENV_VAR = "ONYX_SANDBOX_PUSH_PUBLIC_KEY"


def sidecar_snapshot_restore_path(session_id: UUID | str) -> str:
    return f"{SIDECAR_SNAPSHOT_RESTORE_PREFIX}/{session_id}"


class SnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class FilesystemListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    path: str = ""


class SidecarFilesystemEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    is_directory: bool
    size: int | None = None
    mime_type: str | None = None


class FilesystemListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[SidecarFilesystemEntry]


# Restore has no response body — failures raise, success is the 204.
