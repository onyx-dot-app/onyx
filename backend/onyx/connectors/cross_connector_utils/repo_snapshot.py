"""Local snapshots of repository archives for connectors that index files.

One archive download (e.g. GitHub's tarball endpoint — a single API request)
replaces the per-file content API calls that rate-limit large repositories.
Snapshots are cached on local disk keyed by the caller's cache key, so a
checkpointed connector can read file batches across task invocations without
re-downloading; a cache miss (different worker, prune, restart) just fetches
the archive again.

Archive content is untrusted. Extraction uses tarfile's "data" filter (blocks
absolute paths, traversal, devices, and escaping links) plus archive-wide
member and size caps, walks never follow symlinks, and reads verify that the
resolved path stays inside the snapshot root.
"""

import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

from onyx.configs.app_configs import (
    REPO_SNAPSHOT_MAX_ARCHIVE_MEMBERS,
    REPO_SNAPSHOT_MAX_EXTRACTED_BYTES,
    REPO_SNAPSHOT_TTL_SECONDS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CACHE_ROOT = Path(tempfile.gettempdir()) / "onyx_repo_snapshots"


class RepoSnapshotError(Exception):
    pass


class RepoSnapshot:
    """Read access to one extracted repository revision."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._resolved_root = root.resolve()

    def walk_files(self) -> Iterator[tuple[str, int]]:
        """Yield (repo-relative posix path, size) for every regular file.

        Symlinks are never followed or yielded. Raises RepoSnapshotError if
        the snapshot disappears mid-walk (e.g. pruned by another worker)
        rather than returning a truncated listing.
        """
        _touch(self.root)

        def _on_error(e: OSError) -> None:
            raise RepoSnapshotError(f"Snapshot walk failed: {e}") from e

        root = str(self.root)
        for dirpath, _dirnames, filenames in os.walk(
            root, onerror=_on_error, followlinks=False
        ):
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                try:
                    st = os.lstat(full_path)
                except OSError as e:
                    raise RepoSnapshotError(f"Snapshot walk failed: {e}") from e
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
                yield rel_path, st.st_size

    def read_file(self, rel_path: str, max_size_bytes: int) -> bytes:
        """Read a repo-relative file.

        Refuses paths that resolve outside the snapshot (including through
        symlinks), non-regular files, and files above `max_size_bytes`.
        """
        full_path = (self.root / rel_path).resolve()
        if not full_path.is_relative_to(self._resolved_root):
            raise RepoSnapshotError(f"Path escapes snapshot root: {rel_path}")
        try:
            st = os.lstat(full_path)
            if not stat.S_ISREG(st.st_mode):
                raise RepoSnapshotError(f"Not a regular file: {rel_path}")
            if st.st_size > max_size_bytes:
                raise RepoSnapshotError(
                    f"File exceeds size cap: {rel_path} ({st.st_size}B)"
                )
            with open(full_path, "rb") as f:
                return f.read()
        except OSError as e:
            raise RepoSnapshotError(f"Cannot read {rel_path}: {e}") from e


class _ExtractionLimits:
    """tarfile filter: the "data" filter plus archive-wide member-count and
    total-size caps. Sizes are the header-declared member sizes, which is
    exactly how many bytes tarfile writes per member, so the caps hold
    before any write."""

    def __init__(self) -> None:
        self.members = 0
        self.total_bytes = 0
        self.regular_files = 0

    def __call__(self, member: tarfile.TarInfo, path: str) -> tarfile.TarInfo:
        # Raises FilterError on absolute paths, parent traversal, device
        # nodes, and links escaping the destination.
        filtered = tarfile.data_filter(member, path)
        self.members += 1
        self.total_bytes += max(filtered.size, 0)
        if self.members > REPO_SNAPSHOT_MAX_ARCHIVE_MEMBERS:
            raise RepoSnapshotError(
                f"Archive exceeds {REPO_SNAPSHOT_MAX_ARCHIVE_MEMBERS} members"
            )
        if self.total_bytes > REPO_SNAPSHOT_MAX_EXTRACTED_BYTES:
            raise RepoSnapshotError(
                f"Archive exceeds {REPO_SNAPSHOT_MAX_EXTRACTED_BYTES} extracted bytes"
            )
        if filtered.isreg():
            self.regular_files += 1
        return filtered


def _snapshot_dir(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode()).hexdigest()[:32]
    return _CACHE_ROOT / digest


def _touch(snapshot_root: Path) -> None:
    try:
        os.utime(snapshot_root)
    except OSError as e:
        raise RepoSnapshotError(f"Snapshot is missing: {e}") from e


def _prune_stale_snapshots() -> None:
    """Remove snapshots (and orphaned staging dirs) idle past the TTL."""
    if not _CACHE_ROOT.is_dir():
        return
    cutoff = time.time() - REPO_SNAPSHOT_TTL_SECONDS
    for entry in _CACHE_ROOT.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _extracted_root(tree: Path) -> Path:
    """Repo archives wrap their contents in one top-level directory; the
    snapshot root is that directory when present. lstat: a symlink posing
    as the wrapper must not become the root (resolving it later could
    escape into sibling snapshots)."""
    entries = list(tree.iterdir())
    if len(entries) == 1 and stat.S_ISDIR(os.lstat(entries[0]).st_mode):
        return entries[0]
    return tree


def _publish(root: Path, dest: Path) -> None:
    """Atomically move the extracted tree to `dest`. os.replace refuses to
    overwrite a non-empty directory, so a concurrent miss for the same key
    that published first shows up as OSError; its snapshot is equivalent."""
    try:
        os.replace(root, dest)
    except OSError:
        if not dest.is_dir():
            raise


def _extract_and_publish(archive_path: Path, staging: Path, dest: Path) -> int:
    """Extract the archive under `staging`, then publish it at `dest`.
    Returns the number of regular files extracted."""
    tree = staging / "tree"
    try:
        tree.mkdir()
        limits = _ExtractionLimits()
        with tarfile.open(archive_path, mode="r:gz") as tar:
            # The filter wraps tarfile.data_filter, so the S202 "unsafe
            # extractall" concern (traversal/links/devices) is covered.
            tar.extractall(tree, filter=limits)  # noqa: S202
        if limits.regular_files == 0:
            raise RepoSnapshotError("Archive contains no files")
        _publish(_extracted_root(tree), dest)
    except (tarfile.TarError, OSError) as e:
        raise RepoSnapshotError(f"Failed to extract repo archive: {e}") from e
    return limits.regular_files


def get_or_create_snapshot(
    cache_key: str,
    fetch_archive: Callable[[BinaryIO], None],
) -> RepoSnapshot:
    """Snapshot for `cache_key`, reusing a cached one when present.

    On a miss, `fetch_archive` streams the tar.gz bytes into the file object
    it is given; the archive never has to fit in memory. Errors raised by
    `fetch_archive` propagate unchanged; extraction problems raise
    RepoSnapshotError.
    """
    _prune_stale_snapshots()

    dest = _snapshot_dir(cache_key)
    if dest.is_dir():
        try:
            os.utime(dest)
            return RepoSnapshot(dest)
        except FileNotFoundError:
            pass  # Pruned by another worker between the check and the touch.

    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    # Unique per attempt: concurrent misses for the same key must not share
    # a staging directory.
    staging = dest.with_name(f"{dest.name}.tmp{os.getpid()}_{uuid.uuid4().hex[:8]}")
    staging.mkdir()
    try:
        archive_path = staging / "archive.tar.gz"
        with open(archive_path, "wb") as archive_file:
            fetch_archive(archive_file)
        archive_size = archive_path.stat().st_size
        file_count = _extract_and_publish(archive_path, staging, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    logger.info(
        "Created repo snapshot %s (%s files, %s archived bytes)",
        dest.name,
        file_count,
        archive_size,
    )
    return RepoSnapshot(dest)
