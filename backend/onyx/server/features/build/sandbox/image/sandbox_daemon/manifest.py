"""Outputs manifest for the sandbox daemon.

One call describes the outputs tree of a session: regular files with size,
mtime, and content hash, directories, nothing else, capped by the ceilings
below.

The sandbox agent mutates this filesystem concurrently, so pathname reopens
are a symlink-swap race. Every descent below the anchor and every file open
is fd-relative with O_NOFOLLOW, and file metadata comes from fstat on the
very descriptor being hashed, so a swapped path can only fail the open,
never route the walk or the hash outside outputs.

Runs in-process for the sidecar HTTP route and as ``python -m
sandbox_daemon.manifest <session_id>`` for exec-based backends, both
producing the same contract model.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

from sandbox_daemon.contract import OutputsManifestEntry, OutputsManifestResponse
from sandbox_daemon.snapshot import SESSIONS_ROOT

# Ceilings so a pathological outputs tree cannot stall the daemon or exhaust
# its memory: the response flags truncation instead of growing without bound.
MANIFEST_MAX_ENTRIES = 10_000
MANIFEST_MAX_DEPTH = 64
MANIFEST_MAX_DIR_CHILDREN = 10_000
# Files past the per-file ceiling, or hit once the walk-wide budget is
# spent, are listed with sha256=None rather than read forever (sparse or
# growing files could otherwise stall the walk).
MANIFEST_MAX_HASH_BYTES = 256 * 1024 * 1024
MANIFEST_MAX_TOTAL_HASH_BYTES = 2 * 1024 * 1024 * 1024

_HASH_CHUNK_SIZE = 1024 * 1024

# Vanished, never there, or swapped for a symlink: an empty manifest.
# Anything else (EACCES, EMFILE, EIO) is a real failure the caller must see.
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})


@dataclass
class _Walk:
    response: OutputsManifestResponse = field(
        default_factory=lambda: OutputsManifestResponse(entries=[])
    )
    hash_budget: int = MANIFEST_MAX_TOTAL_HASH_BYTES


class _HashedFile(NamedTuple):
    stat: os.stat_result
    # None means the file was past the hash allowance.
    sha256: str | None
    bytes_read: int


def _hash_regular_file(
    dir_fd: int, name: str, allowed_bytes: int
) -> _HashedFile | None:
    """Open ``name`` relative to ``dir_fd`` and hash it.

    None when the entry is not an openable regular file. O_NONBLOCK keeps a
    raced FIFO swap from blocking the open.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > allowed_bytes:
            return _HashedFile(st, None, 0)
        digest = hashlib.sha256()
        read_total = 0
        while chunk := os.read(fd, _HASH_CHUNK_SIZE):
            digest.update(chunk)
            read_total += len(chunk)
            if read_total > allowed_bytes:
                return _HashedFile(st, None, read_total)
        return _HashedFile(st, digest.hexdigest(), read_total)
    except OSError:
        return None
    finally:
        os.close(fd)


def _utf8_safe(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _walk_directory(walk: _Walk, dir_fd: int, prefix: str, depth: int) -> None:
    """Describe one directory's children, recursing into subdirectories.

    Owns ``dir_fd`` and closes it before returning.
    """
    resp = walk.response
    try:
        try:
            with os.scandir(dir_fd) as it:
                children = sorted(
                    islice(it, MANIFEST_MAX_DIR_CHILDREN + 1),
                    key=lambda e: e.name,
                )
            if len(children) > MANIFEST_MAX_DIR_CHILDREN:
                resp.truncated = True
                children = children[:MANIFEST_MAX_DIR_CHILDREN]
        except OSError:
            # The listing failed after the open, so the directory's contents
            # are unknown: admit the gap instead of looking complete.
            resp.skipped_unreadable += 1
            return
        for child in children:
            if len(resp.entries) >= MANIFEST_MAX_ENTRIES:
                resp.truncated = True
                return
            if not _utf8_safe(child.name):
                resp.skipped_unreadable += 1
                continue
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                # Vanished or unreadable between scandir and stat.
                resp.skipped_unreadable += 1
                continue
            relative = f"{prefix}{child.name}"
            if stat.S_ISLNK(st.st_mode):
                resp.skipped_symlinks += 1
                continue
            if stat.S_ISDIR(st.st_mode):
                if depth >= MANIFEST_MAX_DEPTH:
                    resp.truncated = True
                    continue
                try:
                    child_fd = os.open(
                        child.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=dir_fd,
                    )
                except OSError as e:
                    # ELOOP means it became a symlink between lstat and
                    # open, anything else is simply unreadable.
                    if e.errno == errno.ELOOP:
                        resp.skipped_symlinks += 1
                    else:
                        resp.skipped_unreadable += 1
                    continue
                resp.entries.append(
                    OutputsManifestEntry(
                        path=relative,
                        is_directory=True,
                        mtime_ns=os.fstat(child_fd).st_mtime_ns,
                    )
                )
                _walk_directory(walk, child_fd, f"{relative}/", depth + 1)
                continue
            if not stat.S_ISREG(st.st_mode):
                resp.skipped_special += 1
                continue
            allowed = min(MANIFEST_MAX_HASH_BYTES, walk.hash_budget)
            hashed = _hash_regular_file(dir_fd, child.name, allowed)
            if hashed is None:
                resp.skipped_unreadable += 1
                continue
            walk.hash_budget -= hashed.bytes_read
            resp.entries.append(
                OutputsManifestEntry(
                    path=relative,
                    is_directory=False,
                    size=hashed.stat.st_size,
                    mtime_ns=hashed.stat.st_mtime_ns,
                    sha256=hashed.sha256,
                )
            )
    finally:
        os.close(dir_fd)


def _open_dir_no_follow(name: str | Path, dir_fd: int | None = None) -> int | None:
    """Open a directory refusing symlinks. None means gone or swapped, raises
    on real failures (permissions, fd exhaustion) so they surface instead of
    masquerading as an empty tree. Opens inside the walk instead swallow
    OSError, a partial answer beats none once the walk has begun."""
    try:
        return os.open(
            str(name), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
    except OSError as e:
        if e.errno in _MISSING_ERRNOS:
            return None
        raise


def _open_dir_chain(root: Path, *names: str) -> int | None:
    """Open ``root``, then descend each name fd-relative, refusing symlinks
    at every hop. None when any component is gone."""
    fd = _open_dir_no_follow(root)
    for name in names:
        if fd is None:
            return None
        parent_fd = fd
        try:
            fd = _open_dir_no_follow(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    return fd


def _walk_from_fd(dir_fd: int | None) -> OutputsManifestResponse:
    if dir_fd is None:
        return OutputsManifestResponse(entries=[])
    walk = _Walk()
    _walk_directory(walk, dir_fd, "", depth=0)
    return walk.response


def build_manifest_for_root(root: Path) -> OutputsManifestResponse:
    """Walk ``root`` fd-relative and describe it.

    A missing root is an empty manifest, not an error: a tree that never
    existed has nothing to describe.
    """
    return _walk_from_fd(_open_dir_chain(root))


def build_outputs_manifest(session_id: UUID) -> OutputsManifestResponse:
    """Describe sessions/{sid}/outputs.

    Docker leaves the workspace directory sandbox-owned, so everything under
    it can be swapped. Each hop below the anchor is therefore opened
    fd-relative refusing symlinks, and the anchor's own O_NOFOLLOW is
    defense in depth.
    """
    return _walk_from_fd(
        _open_dir_chain(
            SESSIONS_ROOT.parent,
            SESSIONS_ROOT.name,
            str(session_id),
            "outputs",
        )
    )


if __name__ == "__main__":
    print(build_outputs_manifest(UUID(sys.argv[1])).model_dump_json())
