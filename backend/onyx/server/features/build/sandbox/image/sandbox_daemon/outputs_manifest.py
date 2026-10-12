"""Bounded metadata scan of visible output files.

The agent can change the workspace during a scan. Directory descent uses
fd-relative O_NOFOLLOW opens; metadata reads never follow symlinks or read content.
The sidecar calls this module directly. Docker uses its CLI from root-owned /opt.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from uuid import UUID

from sandbox_daemon.models import (
    MANIFEST_MAX_ENTRIES,
    OutputsManifestEntry,
    OutputsManifestRequest,
    OutputsManifestResponse,
    is_hidden_workspace_name,
)
from sandbox_daemon.snapshot import SESSIONS_ROOT

MANIFEST_MAX_DEPTH = 64
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})


class _Walk:
    def __init__(self, include_web: bool) -> None:
        self.include_web = include_web
        self.remaining = MANIFEST_MAX_ENTRIES
        self.response = OutputsManifestResponse(entries=[])

    def directory(self, dir_fd: int, prefix: str, depth: int) -> None:
        """Scan and close an owned directory descriptor."""
        try:
            with os.scandir(dir_fd) as children:
                while self.remaining > 0:
                    child = next(children, None)
                    if child is None:
                        return
                    self.remaining -= 1
                    if is_hidden_workspace_name(child.name) or (
                        not self.include_web and not prefix and child.name == "web"
                    ):
                        continue
                    if prefix == "web/" and child.name in {
                        "dist",
                        "build",
                        "coverage",
                        "out",
                        "next-env.d.ts",
                        "tsconfig.tsbuildinfo",
                    }:
                        continue
                    try:
                        child.name.encode("utf-8")
                        metadata = child.stat(follow_symlinks=False)
                    except (UnicodeEncodeError, OSError):
                        self.response.complete = False
                        continue
                    relative = f"{prefix}{child.name}"
                    if stat.S_ISDIR(metadata.st_mode):
                        if depth >= MANIFEST_MAX_DEPTH:
                            self.response.complete = False
                            continue
                        try:
                            child_fd = os.open(
                                child.name,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=dir_fd,
                            )
                        except OSError:
                            self.response.complete = False
                            continue
                        self.directory(child_fd, f"{relative}/", depth + 1)
                    elif stat.S_ISREG(metadata.st_mode):
                        self.response.entries.append(
                            OutputsManifestEntry(
                                path=relative,
                                size=metadata.st_size,
                                mtime_ns=metadata.st_mtime_ns,
                                ctime_ns=metadata.st_ctime_ns,
                            )
                        )
                # Do not examine another entry to prove exhaustion at the limit.
                self.response.complete = False
        except OSError:
            self.response.complete = False
        finally:
            os.close(dir_fd)


def _open_directory(name: str | Path, dir_fd: int | None = None) -> int | None:
    """Refuse symlinks; surface real I/O failures instead of an empty scan."""
    try:
        return os.open(
            str(name), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
    except OSError as error:
        if error.errno in _MISSING_ERRNOS:
            return None
        raise


def build_outputs_manifest(
    session_id: UUID, include_web: bool = False
) -> OutputsManifestResponse:
    """Describe outputs without trusting any workspace path component."""
    session_fd = _open_directory(SESSIONS_ROOT.parent)
    for name in (SESSIONS_ROOT.name, str(session_id)):
        if session_fd is None:
            break
        parent_fd = session_fd
        try:
            session_fd = _open_directory(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    if session_fd is None:
        # Another session can wake the sandbox before this workspace is restored.
        return OutputsManifestResponse(entries=[], complete=False)
    try:
        outputs_fd = _open_directory("outputs", dir_fd=session_fd)
    finally:
        os.close(session_fd)
    if outputs_fd is None:
        return OutputsManifestResponse(entries=[])
    walk = _Walk(include_web)
    walk.directory(outputs_fd, "", depth=0)
    walk.response.entries.sort(key=lambda entry: entry.path)
    return walk.response


if __name__ == "__main__":
    import argparse

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Describe a session's output files."
    )
    parser.add_argument("session_id")
    parser.add_argument("--include-web", action="store_true")
    request: OutputsManifestRequest = OutputsManifestRequest.model_validate(
        vars(parser.parse_args())
    )
    print(
        build_outputs_manifest(
            request.session_id, request.include_web
        ).model_dump_json()
    )
