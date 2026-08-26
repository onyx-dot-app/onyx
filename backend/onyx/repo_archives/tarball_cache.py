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
  entries, scoped to that repo's own key prefix. The cache therefore never
  holds more than one archive per repository ever fetched, so it needs no
  separate expiry sweep.

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
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO

from onyx.configs.app_configs import (
    REPO_ARCHIVE_CACHE_MAX_BYTES,
)
from onyx.configs.constants import FileOrigin
from onyx.db.file_record import FileRecordNotFoundError
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
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


def _read_cached_archive(
    file_id: str, max_size_bytes: int, sink: BinaryIO
) -> int | None:
    """Stream a cached archive into `sink` and return its size. None on a
    miss, on an entry the caller's cap excludes, or on any file-store error."""
    try:
        file_store = get_default_file_store()
        try:
            record = file_store.read_file_record(file_id)
        except FileRecordNotFoundError:
            return None
        # Reject an entry another feature wrote under the same id, and check
        # the recorded size before transferring anything: an entry above the
        # caller's cap is a miss (the download path enforces the cap itself).
        size = record.file_size
        if (
            record.file_origin != FileOrigin.REPO_ARCHIVE_CACHE
            or record.file_type != _TARBALL_MIME_TYPE
            or size is None
            or not 0 < size <= max_size_bytes
        ):
            return None
        with file_store.read_file(file_id, mode="b", use_tempfile=True) as cached:
            shutil.copyfileobj(cached, sink)
    except Exception:
        logger.warning("Failed to read cached repo archive %s", file_id, exc_info=True)
        return None
    return size


def _evict_other_revisions(revision: RepoRevision) -> None:
    """One archive per repo: drop the repo's other SHAs before a new one is
    written. Scoped to the repo's own key prefix, so the listing stays small
    on this hot path."""
    repo_prefix = f"{_FILE_ID_PREFIX}{revision.repo.key_prefix}"
    incoming = _file_id(revision)
    stale_ids = [
        record.file_id
        for record in get_default_file_store().list_files_by_prefix(repo_prefix)
        # A revision id is the prefix plus one segment; requiring no "/" in
        # the remainder stops owner="group"/name="sub" evicting the nested
        # repo owner="group/sub"/name="x", whose ids share the prefix.
        if record.file_id != incoming and "/" not in record.file_id[len(repo_prefix) :]
    ]
    delete_files_best_effort(stale_ids, context="repo archive cache")


def _cache_archive(revision: RepoRevision, archive_file: BinaryIO) -> None:
    file_id = _file_id(revision)
    try:
        _evict_other_revisions(revision)
        archive_file.seek(0)
        get_default_file_store().save_file(
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
            cached_size = (
                _read_cached_archive(_file_id(revision), max_size_bytes, archive_file)
                if revision is not None
                else None
            )
            if cached_size is not None:
                size = cached_size
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


def open_repo_archive(
    provider: RepoArchiveProvider,
    repo: RepoRef,
    ref: str | None,
    *,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> AbstractContextManager[RepoArchive]:
    """Tarball of `repo` at `ref` (default branch when None) as a local temp
    file, from the cache when it holds the ref's current commit. Fetched at
    the resolved SHA so what is cached is what was resolved; when resolution
    fails, fetched at the requested ref directly and not cached. The file is
    removed when the block exits."""
    revision = resolve_revision(provider, repo, ref)
    fetch_ref = revision.commit_sha if revision is not None else (ref or "HEAD")
    return _open_archive(provider, repo, fetch_ref, revision, max_size_bytes, timeout)


def open_revision_archive(
    provider: RepoArchiveProvider,
    revision: RepoRevision,
    *,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> AbstractContextManager[RepoArchive]:
    """`open_repo_archive` for a revision already pinned by `resolve_revision`."""
    return _open_archive(
        provider,
        revision.repo,
        revision.commit_sha,
        revision,
        max_size_bytes,
        timeout,
    )
