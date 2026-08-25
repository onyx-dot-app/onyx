"""SHA-addressed cache of GitHub repository tarballs for the coding agent.

Freshness is guaranteed by construction: every fetch first resolves the
requested ref to an immutable commit SHA via the GitHub API (one cheap call),
and the cache is keyed by that SHA. A hit therefore IS the current state of
the ref; a stale cache entry can never be served.

Memory constraints shape the storage choices:
- Archives live in the file store (S3/MinIO), never in process memory or
  Redis. Reads stream through a tempfile, so at most one copy of the archive
  is in memory at a time (the copy the code-interpreter upload requires).
- Only one archive per repository is kept — writing a new SHA deletes the
  previous entries for that repo.
- Archives larger than CODING_AGENT_REPO_CACHE_MAX_BYTES are served but not
  cached, bounding per-entry storage.

Cache failures are never fatal: any file-store or resolution error falls back
to a direct fresh download, which preserves the pre-cache behavior. Concurrent
runs need no locking — same-SHA double-writes collide on the file_id primary
key and are swallowed by the write's error handling, and a reader that loses a
read/evict race falls back to a fresh download.
"""

from dataclasses import replace
from io import BytesIO

from pydantic import BaseModel

from onyx.configs.constants import FileOrigin
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.github import (
    GITHUB_COMMIT_SHA_PATTERN,
    GitHubSource,
    download_github_archive,
    resolve_github_revision,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Archives above this size are downloaded fresh each call but never cached.
CODING_AGENT_REPO_CACHE_MAX_BYTES = 100 * 1024 * 1024

_CACHE_FILE_ID_PREFIX = "coding_agent_repo_cache"
_TARBALL_MIME_TYPE = "application/gzip"


class RepoArchive(BaseModel):
    archive: bytes
    # Resolved commit SHA; None when resolution failed and the requested ref
    # was downloaded directly (uncached).
    commit_sha: str | None


def _repo_cache_prefix(source: GitHubSource) -> str:
    return f"{_CACHE_FILE_ID_PREFIX}/{source.owner}/{source.repo}/"


def _cache_file_id(source: GitHubSource, commit_sha: str) -> str:
    return f"{_repo_cache_prefix(source)}{commit_sha}.tar.gz"


def _resolve_commit_sha(
    source: GitHubSource,
    ref: str | None,
    authorization_header: str | None,
) -> str | None:
    """Resolve ref (branch, SHA, or None for default-branch HEAD) to a full
    commit SHA. None when GitHub can't tell us — callers then download the
    requested ref directly, uncached."""
    try:
        if ref and GITHUB_COMMIT_SHA_PATTERN.fullmatch(ref):
            # A pinned SHA needs no resolution, but the cache may hold a
            # private archive: make one authenticated repo call so a caller
            # without current access cannot read cached source. On failure
            # the download path enforces access on its own, uncached.
            resolve_github_revision(source, authorization_header)
            return ref.lower()
        resolve_source = replace(source, tree_tail=(ref,)) if ref else source
        return resolve_github_revision(resolve_source, authorization_header).revision
    except OnyxError as e:
        logger.warning(
            "Could not resolve %s/%s@%s to a commit SHA (%s); "
            "downloading fresh without caching",
            source.owner,
            source.repo,
            ref or "HEAD",
            e.error_code.value,
        )
        return None


def _read_cached_archive(file_id: str) -> bytes | None:
    try:
        file_store = get_default_file_store()
        if not file_store.has_file(
            file_id=file_id,
            file_origin=FileOrigin.CODING_AGENT_REPO_CACHE,
            file_type=_TARBALL_MIME_TYPE,
        ):
            return None
        # Streams to a tempfile so only the final single copy sits in memory.
        with file_store.read_file(file_id, mode="b", use_tempfile=True) as f:
            return f.read()
    except Exception:
        logger.warning("Failed to read cached repo archive %s", file_id, exc_info=True)
        return None


def _cache_archive(source: GitHubSource, file_id: str, archive: bytes) -> None:
    try:
        file_store = get_default_file_store()
        # One archive per repo: drop older SHAs before writing the new one.
        for record in file_store.list_files_by_prefix(_repo_cache_prefix(source)):
            file_store.delete_file(record.file_id, error_on_missing=False)
        file_store.save_file(
            content=BytesIO(archive),
            display_name=f"{source.owner}/{source.repo} archive",
            file_origin=FileOrigin.CODING_AGENT_REPO_CACHE,
            file_type=_TARBALL_MIME_TYPE,
            file_id=file_id,
        )
    except Exception:
        logger.warning("Failed to cache repo archive %s", file_id, exc_info=True)


def fetch_repo_archive(
    source: GitHubSource,
    ref: str | None,
    authorization_header: str | None,
    max_size_bytes: int,
    timeout: float | tuple[float, float],
) -> RepoArchive:
    """Tarball of `source` at `ref` (default-branch HEAD when None), from the
    cache when it already holds the ref's current commit."""
    commit_sha = _resolve_commit_sha(source, ref, authorization_header)

    if commit_sha is not None:
        file_id = _cache_file_id(source, commit_sha)
        cached = _read_cached_archive(file_id)
        # Empty or caller-oversized entries are misses: the download path
        # then enforces max_size_bytes (and never caches empty archives).
        if cached and len(cached) <= max_size_bytes:
            logger.info("Repo archive cache hit: %s", file_id)
            return RepoArchive(archive=cached, commit_sha=commit_sha)

    # Download at the resolved SHA so what we cache is what we resolved; when
    # resolution failed, download the requested ref directly, uncached.
    archive = download_github_archive(
        source,
        commit_sha or ref or "HEAD",
        authorization_header,
        max_size_bytes=max_size_bytes,
        timeout=timeout,
    )
    if commit_sha is not None and archive:
        if len(archive) <= CODING_AGENT_REPO_CACHE_MAX_BYTES:
            _cache_archive(source, _cache_file_id(source, commit_sha), archive)
        else:
            logger.info(
                "Repo archive for %s/%s@%s exceeds the cache size cap "
                "(%s bytes); not caching",
                source.owner,
                source.repo,
                commit_sha,
                len(archive),
            )
    return RepoArchive(archive=archive, commit_sha=commit_sha)
