"""SHA-addressed cache of repository tarballs in the file store.

Freshness is guaranteed by construction: every fetch first resolves the
requested ref to an immutable commit SHA through the provider (one cheap
call) and the cache is keyed by that SHA. A hit therefore IS the current
state of the ref; a stale entry can never be served. Without a resolved
SHA nothing is cached.

Storage and memory:
- Archives live in the file store (S3/MinIO/...), never in process memory.
  Downloads stream into a local temp file and hits stream out of the store
  into one. The only whole-archive copy in memory is the one the file
  store's save_file makes on a cache write, bounded by
  REPO_ARCHIVE_CACHE_MAX_BYTES.
- One archive per repository: writing a new SHA deletes the repo's older
  entries. Entries older than REPO_ARCHIVE_CACHE_TTL_SECONDS are pruned on
  the next write, so repos nobody asks about again do not accumulate.

Cache failures are never fatal: any file-store or resolution error falls back
to a direct fresh download. Concurrent runs need no locking: save_file is an
upsert, so same-SHA double-writes both succeed, and a reader that loses a
read/evict race falls back to a fresh download. Two runs at different SHAs
can leave a record without a backing object; its next read fails, falls back
to a download, and re-caches.
"""

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from onyx.configs.app_configs import (
    REPO_ARCHIVE_CACHE_MAX_BYTES,
    REPO_ARCHIVE_CACHE_TTL_SECONDS,
)
from onyx.configs.constants import FileOrigin
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.repo_archives.models import RepoArchive, RepoRef, RepoRevision
from onyx.repo_archives.provider import RepoArchiveProvider
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FILE_ID_PREFIX = "repo_archive_cache/"
_TARBALL_MIME_TYPE = "application/gzip"


def _file_id(revision: RepoRevision) -> str:
    return f"{_FILE_ID_PREFIX}{revision.key}.tar.gz"


def resolve_revision(
    provider: RepoArchiveProvider, repo: RepoRef, ref: str | None
) -> RepoRevision | None:
    """Pin `ref` (branch, tag, SHA, or None for the default branch) to its
    current commit. None when the provider can't tell us; callers then fetch
    the requested ref directly, uncached."""
    try:
        return RepoRevision(repo=repo, commit_sha=provider.resolve_commit(repo, ref))
    except OnyxError as e:
        # Anonymous API calls share a small per-IP budget; once it is spent
        # every run lands here and pays for a full download.
        limit_hint = "" if provider.authenticated else " (anonymous API rate limit?)"
        logger.warning(
            "Could not resolve %s@%s to a commit SHA (%s)%s; "
            "fetching fresh without caching",
            repo.display,
            ref or "HEAD",
            e.error_code.value,
            limit_hint,
        )
        return None


def _file_size(archive_file: BinaryIO) -> int:
    archive_file.seek(0, 2)
    size = archive_file.tell()
    archive_file.seek(0)
    return size


def _read_cached_archive(file_id: str, max_size_bytes: int, sink: BinaryIO) -> bool:
    """Stream a cached archive into `sink`. False on a miss, on an entry the
    caller's cap excludes, or on any file-store error."""
    try:
        file_store = get_default_file_store()
        if not file_store.has_file(
            file_id=file_id,
            file_origin=FileOrigin.REPO_ARCHIVE_CACHE,
            file_type=_TARBALL_MIME_TYPE,
        ):
            return False
        # Check the recorded size before transferring anything: an entry
        # above the caller's cap is a miss (the download path enforces the
        # cap itself). A null size is a legacy row; measure after the copy.
        recorded_size = file_store.read_file_record(file_id).file_size
        if recorded_size is not None and not 0 < recorded_size <= max_size_bytes:
            return False
        with file_store.read_file(file_id, mode="b", use_tempfile=True) as cached:
            shutil.copyfileobj(cached, sink)
    except Exception:
        logger.warning("Failed to read cached repo archive %s", file_id, exc_info=True)
        return False
    return 0 < _file_size(sink) <= max_size_bytes


def _evict_stale_entries(file_store: FileStore, repo: RepoRef) -> None:
    """One archive per repo: drop the repo's older SHAs. Also prune every
    repo's entries older than the TTL so abandoned repos do not accumulate."""
    repo_prefix = f"{_FILE_ID_PREFIX}{repo.key_prefix}"
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=REPO_ARCHIVE_CACHE_TTL_SECONDS
    )
    for record in file_store.list_files_by_prefix(_FILE_ID_PREFIX):
        if record.file_id.startswith(repo_prefix) or record.updated_at < cutoff:
            file_store.delete_file(record.file_id, error_on_missing=False)


def _cache_archive(revision: RepoRevision, archive_file: BinaryIO) -> None:
    file_id = _file_id(revision)
    try:
        file_store = get_default_file_store()
        _evict_stale_entries(file_store, revision.repo)
        archive_file.seek(0)
        file_store.save_file(
            content=archive_file,
            display_name=f"{revision.repo.display} archive",
            file_origin=FileOrigin.REPO_ARCHIVE_CACHE,
            file_type=_TARBALL_MIME_TYPE,
            file_id=file_id,
        )
    except Exception:
        logger.warning("Failed to cache repo archive %s", file_id, exc_info=True)


@contextmanager
def _open_archive(
    provider: RepoArchiveProvider,
    repo: RepoRef,
    ref: str,
    revision: RepoRevision | None,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> Iterator[RepoArchive]:
    with tempfile.TemporaryDirectory(prefix="onyx_repo_archive_") as tmp_dir:
        path = Path(tmp_dir) / "repo.tar.gz"
        with open(path, "w+b") as archive_file:
            cached = revision is not None and _read_cached_archive(
                _file_id(revision), max_size_bytes, archive_file
            )
            if cached:
                size = _file_size(archive_file)
                logger.info("Repo archive cache hit: %s@%s", repo.display, ref)
            else:
                archive_file.seek(0)
                archive_file.truncate()
                size = provider.stream_archive(
                    repo,
                    ref,
                    archive_file,
                    max_size_bytes=max_size_bytes,
                    timeout=timeout,
                )
                archive_file.flush()
                if revision is not None and size:
                    if size <= REPO_ARCHIVE_CACHE_MAX_BYTES:
                        _cache_archive(revision, archive_file)
                    else:
                        logger.info(
                            "Repo archive %s@%s exceeds the cache size cap "
                            "(%s bytes); not caching",
                            repo.display,
                            ref,
                            size,
                        )
        yield RepoArchive(path=path, size=size, revision=revision)


@contextmanager
def open_repo_archive(
    provider: RepoArchiveProvider,
    repo: RepoRef,
    ref: str | None,
    *,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> Iterator[RepoArchive]:
    """Tarball of `repo` at `ref` (default branch when None) as a local temp
    file, from the cache when it holds the ref's current commit. Fetched at
    the resolved SHA so what is cached is what was resolved; when resolution
    fails, fetched at the requested ref directly and not cached. The file is
    removed when the block exits."""
    revision = resolve_revision(provider, repo, ref)
    fetch_ref = revision.commit_sha if revision is not None else (ref or "HEAD")
    with _open_archive(
        provider, repo, fetch_ref, revision, max_size_bytes, timeout
    ) as archive:
        yield archive


@contextmanager
def open_revision_archive(
    provider: RepoArchiveProvider,
    revision: RepoRevision,
    *,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> Iterator[RepoArchive]:
    """`open_repo_archive` for a revision already pinned by `resolve_revision`."""
    with _open_archive(
        provider,
        revision.repo,
        revision.commit_sha,
        revision,
        max_size_bytes,
        timeout,
    ) as archive:
        yield archive
