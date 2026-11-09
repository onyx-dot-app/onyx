"""HTTP models and route constants shared by the sandbox daemon and API server.

Both sides import these constants and request models to keep the sidecar wire
contract in sync. The daemon imports this as ``sandbox_daemon.models`` (the
Dockerfile copies ``sandbox_daemon/`` to ``/workspace/sandbox_daemon/``); the
api-server imports the full module path.
"""

from collections.abc import Iterator
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict

SIDECAR_HEALTH_PATH = "/health"
SIDECAR_READY_PATH = "/ready"
SIDECAR_PUSH_PATH = "/push"
PUSH_DAEMON_PORT = 8731
SIDECAR_FILESYSTEM_LIST_PATH = "/filesystem/list"
SIDECAR_OUTPUTS_MANIFEST_PATH = "/filesystem/outputs-manifest"
# Count all examined entries, including directories and ignored names.
MANIFEST_MAX_ENTRIES = 10_000
SIDECAR_SNAPSHOT_CREATE_PATH = "/snapshot/create"
SIDECAR_SNAPSHOT_RESTORE_PREFIX = "/snapshot/restore"
SIDECAR_SNAPSHOT_RESTORE_ROUTE = f"{SIDECAR_SNAPSHOT_RESTORE_PREFIX}/{{session_id}}"
SIDECAR_OPENCODE_HISTORY_CREATE_PATH = "/opencode-history/create"
SIDECAR_OPENCODE_HISTORY_RESTORE_PATH = "/opencode-history/restore"
SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH = "/opencode-history/mark-restored"
SIDECAR_PUSH_PUBLIC_KEY_ENV_VAR = "ONYX_SANDBOX_PUSH_PUBLIC_KEY"

# Push limits. Runtime Skill selection (onyx/skills/push.py) leaves out whole
# Skills to stay within content, file, folder and path limits; transport
# checks the same bounds.
PUSH_MAX_CONTENT_BYTES = 900 * 1024 * 1024
PUSH_MAX_FILES = 10_000
# Parent directories are implied by file paths, so they are counted apart.
PUSH_MAX_DIRECTORIES = 10_000
PUSH_MAX_PATH_BYTES = 4096
PUSH_MAX_COMPONENT_BYTES = 255
# Linux PATH_MAX includes the trailing NUL; reserve the extraction root too.
_PUSH_MAX_ABSOLUTE_PATH_BYTES = 4095
PUSH_VERSION_NAME_BYTES = 25
# One tar entry: 512-byte header, up to 511 bytes of data padding, and a PAX
# header plus records for a path of PUSH_MAX_PATH_BYTES (512 + 9 x 512).
_TAR_ENTRY_OVERHEAD_BYTES = 6 * 1024
# End-of-archive blocks plus padding to the 10 KiB tar record size.
_TAR_END_OVERHEAD_BYTES = 20 * 1024
PUSH_MAX_TAR_BYTES = (
    PUSH_MAX_CONTENT_BYTES
    + PUSH_MAX_FILES * _TAR_ENTRY_OVERHEAD_BYTES
    + _TAR_END_OVERHEAD_BYTES
)
# zlib deflateBound for incompressible input, plus gzip header and trailer.
PUSH_MAX_ARCHIVE_BYTES = (
    PUSH_MAX_TAR_BYTES
    + (PUSH_MAX_TAR_BYTES >> 12)
    + (PUSH_MAX_TAR_BYTES >> 14)
    + (PUSH_MAX_TAR_BYTES >> 25)
    + 1024
)


def push_version_directory(mount_path: str, version: str) -> PurePosixPath:
    mount = PurePosixPath(mount_path)
    return mount.parent / ".versions" / mount.name / version


def push_path_byte_limit(extraction_root: str) -> int:
    return min(
        PUSH_MAX_PATH_BYTES,
        _PUSH_MAX_ABSOLUTE_PATH_BYTES - len(extraction_root.encode("utf-8")) - 1,
    )


def validate_push_path(path: str, max_path_bytes: int) -> None:
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Non-UTF-8 path name") from exc
    if len(encoded) > max_path_bytes:
        raise ValueError(f"Path name longer than {max_path_bytes} bytes")
    if any(
        len(part.encode("utf-8")) > PUSH_MAX_COMPONENT_BYTES for part in path.split("/")
    ):
        raise ValueError(f"Path component longer than {PUSH_MAX_COMPONENT_BYTES} bytes")


def push_parent_directories(path: str) -> Iterator[str]:
    """Implied folders, nearest first; a known folder implies known ancestors."""
    for parent in PurePosixPath(path).parents:
        if parent == PurePosixPath("."):
            break
        yield str(parent)


_HIDDEN_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
        "opencode.json",
        "nextjs.log",
        "nextjs.pid",
    }
)


WEB_GENERATED_NAMES = frozenset(
    {"dist", "build", "coverage", "out", "next-env.d.ts", "tsconfig.tsbuildinfo"}
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
    include_web: bool = False


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
