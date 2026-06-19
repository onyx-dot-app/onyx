"""Filesystem listing operations for the sandbox sidecar."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import UUID

from sandbox_daemon.contract import FilesystemListResponse
from sandbox_daemon.contract import SidecarFilesystemEntry
from sandbox_daemon.snapshot import SESSIONS_ROOT

_USER_LIBRARY_LINK_TARGET = Path("/workspace/managed/user_library")


class FilesystemPathError(RuntimeError):
    """Raised for invalid, missing, or non-directory paths."""


def _clean_relative_path(path: str) -> Path:
    if "\x00" in path:
        raise FilesystemPathError("path not found or not a directory")

    path_obj = Path(path.lstrip("/"))
    if any(part == ".." for part in path_obj.parts):
        raise FilesystemPathError("path traversal is not allowed")

    parts = [part for part in path_obj.parts if part not in ("", ".")]
    return Path(*parts) if parts else Path(".")


def _is_managed_user_library_link(entry: Path) -> bool:
    if not entry.is_symlink() or entry.name != "user_library":
        return False
    try:
        return entry.readlink() == _USER_LIBRARY_LINK_TARGET
    except OSError:
        return False


def _is_user_library_request(relative_path: Path, session_root: Path) -> bool:
    return relative_path.parts[:1] == (
        "user_library",
    ) and _is_managed_user_library_link(session_root / "user_library")


def _resolved_user_library_root() -> Path | None:
    try:
        resolved = _USER_LIBRARY_LINK_TARGET.resolve(strict=True)
        versions_root = (_USER_LIBRARY_LINK_TARGET.parent / ".versions").resolve(
            strict=True
        )
    except (OSError, ValueError):
        return None

    if resolved.is_dir() and resolved.is_relative_to(versions_root):
        return resolved
    return None


def _resolve_allowed_directory(
    path: Path,
    session_root_resolved: Path,
    *,
    allow_user_library: bool,
) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError):
        return None

    if not resolved.is_dir():
        return None

    if resolved.is_relative_to(session_root_resolved):
        return resolved

    if allow_user_library:
        user_library_root = _resolved_user_library_root()
        if user_library_root is not None and resolved.is_relative_to(user_library_root):
            return resolved

    return None


def _entry_size(entry: Path, is_directory: bool) -> int | None:
    if is_directory:
        return None
    try:
        stat_result = entry.lstat() if entry.is_symlink() else entry.stat()
        return stat_result.st_size
    except OSError:
        return None


def list_session_directory(session_id: UUID, path: str) -> FilesystemListResponse:
    relative_path = _clean_relative_path(path)
    try:
        session_root_resolved = SESSIONS_ROOT.resolve(strict=True) / str(session_id)
    except OSError as e:
        raise FilesystemPathError("path not found or not a directory") from e

    session_root = SESSIONS_ROOT / str(session_id)
    if session_root.is_symlink():
        raise FilesystemPathError("session path is a symlink")
    target = session_root / relative_path
    allow_user_library = _is_user_library_request(relative_path, session_root)

    target_directory = _resolve_allowed_directory(
        target,
        session_root_resolved,
        allow_user_library=allow_user_library,
    )
    if target_directory is None:
        raise FilesystemPathError("path not found or not a directory")

    base_path = "" if relative_path == Path(".") else relative_path.as_posix()
    entries: list[SidecarFilesystemEntry] = []
    is_listing_session_root = target_directory == session_root_resolved
    for entry_path_on_disk in target_directory.iterdir():
        name = entry_path_on_disk.name
        is_managed_user_library = (
            is_listing_session_root
            and _is_managed_user_library_link(entry_path_on_disk)
        )
        child_allow_user_library = allow_user_library or is_managed_user_library
        is_directory = (
            _resolve_allowed_directory(
                entry_path_on_disk,
                session_root_resolved,
                allow_user_library=child_allow_user_library,
            )
            is not None
        )
        if (
            not is_directory
            and is_managed_user_library
            and not _USER_LIBRARY_LINK_TARGET.exists()
        ):
            # Keep restored-session placeholders visible as folders while
            # hydration recreates the managed user library target.
            is_directory = True

        entry_path = f"{base_path}/{name}".lstrip("/")
        entries.append(
            SidecarFilesystemEntry(
                name=name,
                path=entry_path,
                is_directory=is_directory,
                size=_entry_size(entry_path_on_disk, is_directory),
                mime_type=None if is_directory else mimetypes.guess_type(name)[0],
            )
        )

    entries.sort(key=lambda e: (not e.is_directory, e.name.lower(), e.name))
    return FilesystemListResponse(entries=entries)
