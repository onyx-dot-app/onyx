from collections.abc import Iterator
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from onyx.coding_agent.repo_cache import (
    CODING_AGENT_REPO_CACHE_MAX_BYTES,
    _cache_file_id,
    fetch_repo_archive,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.github import GitHubRevision, GitHubSource

SOURCE = GitHubSource(owner="test-org", repo="test-repo")
SHA = "a" * 40
ARCHIVE = b"tarball-bytes"

MODULE = "onyx.coding_agent.repo_cache"


@pytest.fixture
def mock_file_store() -> Iterator[MagicMock]:
    store = MagicMock()
    store.has_file.return_value = False
    store.list_files_by_prefix.return_value = []
    with patch(f"{MODULE}.get_default_file_store", return_value=store):
        yield store


def _patch_resolve(sha: str | None = SHA):
    if sha is None:
        return patch(
            f"{MODULE}.resolve_github_revision",
            side_effect=OnyxError(OnyxErrorCode.NOT_FOUND),
        )
    return patch(
        f"{MODULE}.resolve_github_revision",
        return_value=GitHubRevision(revision=sha, subpath=None),
    )


def _fetch(ref: str | None = None) -> tuple:
    result = fetch_repo_archive(
        SOURCE,
        ref,
        authorization_header=None,
        max_size_bytes=500 * 1024 * 1024,
        timeout=30,
    )
    return result.archive, result.commit_sha


def test_cache_miss_downloads_and_saves(mock_file_store: MagicMock) -> None:
    with (
        _patch_resolve(),
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE) as download,
    ):
        archive, sha = _fetch()

    assert (archive, sha) == (ARCHIVE, SHA)
    # Downloaded at the resolved SHA, not at HEAD — what we cache is what we
    # resolved.
    assert download.call_args.args[1] == SHA
    mock_file_store.save_file.assert_called_once()
    assert mock_file_store.save_file.call_args.kwargs["file_id"] == _cache_file_id(
        SOURCE, SHA
    )


def test_cache_hit_skips_download(mock_file_store: MagicMock) -> None:
    mock_file_store.has_file.return_value = True
    mock_file_store.read_file.return_value = BytesIO(ARCHIVE)

    with (
        _patch_resolve(),
        patch(f"{MODULE}.download_github_archive") as download,
    ):
        archive, sha = _fetch()

    assert (archive, sha) == (ARCHIVE, SHA)
    download.assert_not_called()
    mock_file_store.save_file.assert_not_called()


def test_new_sha_evicts_previous_entries(mock_file_store: MagicMock) -> None:
    old_record = MagicMock()
    old_record.file_id = _cache_file_id(SOURCE, "b" * 40)
    mock_file_store.list_files_by_prefix.return_value = [old_record]

    with (
        _patch_resolve(),
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE),
    ):
        _fetch()

    mock_file_store.delete_file.assert_called_once_with(
        old_record.file_id, error_on_missing=False
    )
    mock_file_store.save_file.assert_called_once()


def test_oversized_archive_is_not_cached(mock_file_store: MagicMock) -> None:
    big = b"x" * (CODING_AGENT_REPO_CACHE_MAX_BYTES + 1)
    with (
        _patch_resolve(),
        patch(f"{MODULE}.download_github_archive", return_value=big),
    ):
        archive, sha = _fetch()

    assert (archive, sha) == (big, SHA)
    mock_file_store.save_file.assert_not_called()


def test_resolution_failure_falls_back_to_fresh_download(
    mock_file_store: MagicMock,
) -> None:
    with (
        _patch_resolve(sha=None),
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE) as download,
    ):
        archive, sha = _fetch(ref="feature-branch")

    assert (archive, sha) == (ARCHIVE, None)
    # Downloaded at the requested ref; nothing cached without a SHA.
    assert download.call_args.args[1] == "feature-branch"
    mock_file_store.save_file.assert_not_called()


def test_pinned_sha_keeps_sha_but_proves_access(mock_file_store: MagicMock) -> None:
    with (
        patch(f"{MODULE}.resolve_github_revision") as resolve,
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE),
    ):
        _, sha = _fetch(ref=SHA.upper())

    # The pinned SHA is used as-is, but one authenticated repo call still
    # runs so a caller without current access cannot read cached source.
    resolve.assert_called_once()
    assert sha == SHA
    # A pinned SHA still populates the cache on a miss.
    mock_file_store.save_file.assert_called_once()


def test_pinned_sha_without_access_bypasses_cache(mock_file_store: MagicMock) -> None:
    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    with (
        patch(
            f"{MODULE}.resolve_github_revision",
            side_effect=OnyxError(OnyxErrorCode.NOT_FOUND, "no access"),
        ),
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE) as download,
    ):
        archive, sha = _fetch(ref=SHA)

    # Access check failed: the cache is never consulted and the download
    # itself must enforce access.
    mock_file_store.has_file.assert_not_called()
    assert (archive, sha) == (ARCHIVE, None)
    download.assert_called_once()


def test_file_store_failure_falls_back_to_download(
    mock_file_store: MagicMock,
) -> None:
    mock_file_store.has_file.side_effect = RuntimeError("store down")
    mock_file_store.save_file.side_effect = RuntimeError("store down")

    with (
        _patch_resolve(),
        patch(f"{MODULE}.download_github_archive", return_value=ARCHIVE),
    ):
        archive, sha = _fetch()

    assert (archive, sha) == (ARCHIVE, SHA)
