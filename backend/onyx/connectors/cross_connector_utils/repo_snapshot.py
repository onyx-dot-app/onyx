"""Local snapshots of repository archives for connectors that index files.

One archive download (e.g. GitHub's tarball endpoint — a single API request)
replaces the per-file content API calls that rate-limit large repositories.
Snapshots are cached on local disk keyed by the caller's cache key, so a
checkpointed connector can read file batches across task invocations without
re-downloading; a cache miss (different worker, prune, restart) just fetches
the archive again.

Archive content is untrusted. Extraction uses tarfile's "data" filter (blocks
absolute paths, traversal, devices, and escaping links), walks never follow
symlinks, and reads re-verify that the resolved path stays inside the
snapshot root.
"""

import hashlib
import io
import os
import shutil
import stat
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Snapshots untouched for this long are pruned on the next cache access.
_SNAPSHOT_TTL_SECONDS = 6 * 60 * 60
_CACHE_ROOT = Path(tempfile.gettempdir()) / "onyx_repo_snapshots"
# Extraction bounds: a small, highly compressible archive must not exhaust
# worker disk or time. Sizes are the header-declared member sizes, which is
# exactly how many bytes tarfile writes per member.
_MAX_ARCHIVE_MEMBERS = 200_000
_MAX_EXTRACTED_BYTES = 2 * 1024**3


class RepoSnapshotError(Exception):
    pass


def _snapshot_dir(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode()).hexdigest()[:32]
    return _CACHE_ROOT / digest


def _prune_stale_snapshots() -> None:
    if not _CACHE_ROOT.is_dir():
        return
    cutoff = time.time() - _SNAPSHOT_TTL_SECONDS
    for entry in _CACHE_ROOT.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _limits_filter() -> Callable[[tarfile.TarInfo, str], tarfile.TarInfo | None]:
    """The "data" filter plus archive-wide member-count and total-size caps."""
    member_count = 0
    total_bytes = 0

    def _filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
        nonlocal member_count, total_bytes
        # data_filter: rejects absolute paths, parent traversal, device
        # nodes, and links escaping the destination.
        filtered = tarfile.data_filter(member, path)
        if filtered is None:
            return None
        member_count += 1
        total_bytes += max(filtered.size, 0)
        if member_count > _MAX_ARCHIVE_MEMBERS:
            raise RepoSnapshotError(f"Archive exceeds {_MAX_ARCHIVE_MEMBERS} members")
        if total_bytes > _MAX_EXTRACTED_BYTES:
            raise RepoSnapshotError(
                f"Archive exceeds {_MAX_EXTRACTED_BYTES} extracted bytes"
            )
        return filtered

    return _filter


def _extract_archive(archive: bytes, dest: Path) -> None:
    """Safely extract a tar.gz archive, stripping the single top-level
    directory that repo archives conventionally wrap their contents in."""
    # Unique per attempt: concurrent misses for the same key must not share
    # a staging directory. The loser's os.replace publishes second; both
    # extractions are complete, so either result is valid.
    staging = dest.with_name(f"{dest.name}.tmp{os.getpid()}_{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            # The callable wraps tarfile.data_filter, so the S202 "unsafe
            # extractall" concern (traversal/links/devices) is covered.
            tar.extractall(staging, filter=_limits_filter())  # noqa: S202

        entries = list(staging.iterdir())
        # lstat: a symlink posing as the single top-level entry must not
        # become the snapshot root (resolving it later could escape into
        # sibling snapshots).
        if len(entries) == 1 and stat.S_ISDIR(os.lstat(entries[0]).st_mode):
            root = entries[0]
        else:
            root = staging
        os.replace(root, dest)
    except (tarfile.TarError, OSError) as e:
        raise RepoSnapshotError(f"Failed to extract repo archive: {e}") from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def get_or_create_snapshot(
    cache_key: str,
    fetch_archive: Callable[[], bytes],
) -> Path:
    """Root directory of a local snapshot for `cache_key`, reusing a cached
    one when present; otherwise `fetch_archive` supplies the tar.gz bytes."""
    _prune_stale_snapshots()

    dest = _snapshot_dir(cache_key)
    if dest.is_dir():
        os.utime(dest)
        return dest

    archive = fetch_archive()
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    _extract_archive(archive, dest)
    logger.info(
        "Created repo snapshot for %s (%s bytes archived)", cache_key, len(archive)
    )
    return dest


def remove_snapshot(cache_key: str) -> None:
    shutil.rmtree(_snapshot_dir(cache_key), ignore_errors=True)


def walk_snapshot_files(snapshot_root: Path) -> Iterator[tuple[str, int]]:
    """Yield (repo-relative posix path, size) for every regular file in the
    snapshot. Symlinks are never followed or yielded."""
    root = str(snapshot_root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            try:
                st = os.lstat(full_path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
            yield rel_path, st.st_size


def read_snapshot_file(
    snapshot_root: Path,
    rel_path: str,
    max_size_bytes: int,
) -> bytes:
    """Read a repo-relative file, refusing symlinks, path escapes, and
    oversized files."""
    resolved_root = snapshot_root.resolve()
    # Refuse symlink components lexically, before resolve() would silently
    # follow them (resolve replaces a symlink with its target).
    current = snapshot_root
    for part in Path(rel_path).parts:
        if part in ("..", "."):
            raise RepoSnapshotError(f"Invalid path component: {rel_path}")
        current = current / part
        if os.path.islink(current):
            raise RepoSnapshotError(f"Symlink in path: {rel_path}")
    full_path = current.resolve()
    if not full_path.is_relative_to(resolved_root):
        raise RepoSnapshotError(f"Path escapes snapshot root: {rel_path}")

    st = os.lstat(full_path)
    if not stat.S_ISREG(st.st_mode):
        raise RepoSnapshotError(f"Not a regular file: {rel_path}")
    if st.st_size > max_size_bytes:
        raise RepoSnapshotError(f"File exceeds size cap: {rel_path} ({st.st_size}B)")

    with open(full_path, "rb") as f:
        return f.read()
