from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import FileOrigin
from onyx.db.file_record import FileRecordNotFoundError
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.repo_archives import tarball_cache
from onyx.repo_archives.models import RepoRef
from onyx.repo_archives.tarball_cache import (
    _file_id,
    open_repo_archive,
    open_revision_archive,
    resolve_revision,
)
from tests.utils.repo_archives import TEST_REPO, FakeArchiveProvider, revision

SHA = "a" * 40
ARCHIVE = b"tarball-bytes"
MAX_BYTES = 500 * 1024 * 1024
MODULE = "onyx.repo_archives.tarball_cache"


@pytest.fixture
def mock_file_store() -> Iterator[MagicMock]:
    store = MagicMock()
    store.read_file_record.side_effect = FileRecordNotFoundError("miss")
    store.list_files_by_prefix.return_value = []
    with patch(f"{MODULE}.get_default_file_store", return_value=store):
        yield store


@pytest.fixture
def mock_delete_files() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.delete_files_best_effort") as delete_files:
        yield delete_files


def _provider(resolve_error: OnyxError | None = None) -> FakeArchiveProvider:
    return FakeArchiveProvider(
        archives={SHA: ARCHIVE, "feature-branch": ARCHIVE},
        refs={None: SHA, "main": SHA},
        resolve_error=resolve_error,
    )


def _cached(store: MagicMock, archive: bytes = ARCHIVE) -> None:
    store.read_file_record.side_effect = None
    store.read_file_record.return_value = MagicMock(
        file_origin=FileOrigin.REPO_ARCHIVE_CACHE,
        file_type=tarball_cache._TARBALL_MIME_TYPE,
        file_size=len(archive),
    )
    store.read_file.return_value = BytesIO(archive)


def _record(file_id: str, age: timedelta = timedelta(0)) -> MagicMock:
    record = MagicMock()
    record.file_id = file_id
    record.updated_at = datetime.now(timezone.utc) - age
    return record


def _fetch(
    provider: FakeArchiveProvider, ref: str | None = None
) -> tuple[bytes, str | None, Path]:
    with open_repo_archive(
        provider, TEST_REPO, ref, max_size_bytes=MAX_BYTES, timeout=30
    ) as result:
        assert result.size == result.path.stat().st_size
        sha = result.revision.commit_sha if result.revision else None
        return result.path.read_bytes(), sha, result.path


def test_cache_miss_downloads_and_saves(mock_file_store: MagicMock) -> None:
    saved: list[bytes] = []
    mock_file_store.save_file.side_effect = lambda **kw: saved.append(
        kw["content"].read()
    )
    provider = _provider()

    archive, sha, path = _fetch(provider)

    assert (archive, sha) == (ARCHIVE, SHA)
    # Downloaded at the resolved SHA, not at HEAD — what we cache is what we
    # resolved.
    assert provider.downloads == [SHA]
    save_kwargs = mock_file_store.save_file.call_args.kwargs
    assert save_kwargs["file_id"] == _file_id(revision(SHA))
    assert saved == [ARCHIVE]
    # The temp file is gone once the block exits.
    assert not path.exists()


def test_cache_hit_skips_download(mock_file_store: MagicMock) -> None:
    _cached(mock_file_store)
    provider = _provider()

    archive, sha, _ = _fetch(provider)

    assert (archive, sha) == (ARCHIVE, SHA)
    assert provider.downloads == []
    mock_file_store.save_file.assert_not_called()


def test_open_revision_archive_skips_resolution(mock_file_store: MagicMock) -> None:
    _cached(mock_file_store)
    provider = _provider()

    with open_revision_archive(
        provider, revision(SHA), max_size_bytes=MAX_BYTES, timeout=30
    ) as result:
        assert result.path.read_bytes() == ARCHIVE
        assert result.revision == revision(SHA)
    assert provider.resolve_calls == 0
    assert provider.downloads == []


def test_cached_entry_above_caller_cap_is_skipped_without_transfer(
    mock_file_store: MagicMock,
) -> None:
    _cached(mock_file_store)
    mock_file_store.read_file_record.return_value.file_size = MAX_BYTES + 1
    provider = _provider()

    archive, _, _ = _fetch(provider)

    assert archive == ARCHIVE
    mock_file_store.read_file.assert_not_called()
    assert provider.downloads == [SHA]


def test_new_sha_evicts_previous_entries(
    mock_file_store: MagicMock, mock_delete_files: MagicMock
) -> None:
    old_record = _record(_file_id(revision("b" * 40)))
    other_repo = RepoRef(provider="test", host="test.local", owner="other", name="r")
    other_record = _record(_file_id(revision("c" * 40, other_repo)))
    mock_file_store.list_files_by_prefix.return_value = [old_record, other_record]

    _fetch(_provider())

    assert mock_delete_files.call_args.args[0] == [old_record.file_id]
    mock_file_store.save_file.assert_called_once()


def test_entries_older_than_ttl_are_pruned(
    mock_file_store: MagicMock, mock_delete_files: MagicMock
) -> None:
    ttl = timedelta(seconds=tarball_cache.REPO_ARCHIVE_CACHE_TTL_SECONDS)
    old_repo = RepoRef(provider="test", host="test.local", owner="old", name="r")
    new_repo = RepoRef(provider="test", host="test.local", owner="new", name="r")
    stale = _record(
        _file_id(revision("d" * 40, old_repo)), age=ttl + timedelta(minutes=1)
    )
    fresh = _record(
        _file_id(revision("e" * 40, new_repo)), age=ttl - timedelta(minutes=1)
    )
    mock_file_store.list_files_by_prefix.return_value = [stale, fresh]

    _fetch(_provider())

    assert mock_delete_files.call_args.args[0] == [stale.file_id]


def test_oversized_archive_is_not_cached(
    mock_file_store: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tarball_cache, "REPO_ARCHIVE_CACHE_MAX_BYTES", 4)

    archive, sha, _ = _fetch(_provider())

    assert (archive, sha) == (ARCHIVE, SHA)
    mock_file_store.save_file.assert_not_called()


def test_resolution_failure_falls_back_to_fresh_download(
    mock_file_store: MagicMock,
) -> None:
    provider = _provider(resolve_error=OnyxError(OnyxErrorCode.NOT_FOUND))

    archive, sha, _ = _fetch(provider, ref="feature-branch")

    assert (archive, sha) == (ARCHIVE, None)
    # Downloaded at the requested ref; nothing cached without a SHA.
    assert provider.downloads == ["feature-branch"]
    mock_file_store.read_file_record.assert_not_called()
    mock_file_store.save_file.assert_not_called()


def test_resolve_revision_returns_none_on_provider_error() -> None:
    provider = _provider(resolve_error=OnyxError(OnyxErrorCode.RATE_LIMITED))
    assert resolve_revision(provider, TEST_REPO, "main") is None
    assert resolve_revision(_provider(), TEST_REPO, "main") == revision(SHA)


def test_pinned_sha_keeps_sha_but_proves_access(mock_file_store: MagicMock) -> None:
    provider = _provider()

    _, sha, _ = _fetch(provider, ref=SHA.upper())

    # The pinned SHA is used as-is, but one provider call still runs so a
    # caller without current access cannot read cached source.
    assert provider.resolve_calls == 1
    assert sha == SHA
    # A pinned SHA still populates the cache on a miss.
    mock_file_store.save_file.assert_called_once()


def test_pinned_sha_without_access_bypasses_cache(mock_file_store: MagicMock) -> None:
    provider = _provider(resolve_error=OnyxError(OnyxErrorCode.NOT_FOUND, "no access"))

    archive, sha, _ = _fetch(provider, ref=SHA)

    # Access check failed: the cache is never consulted and the download
    # itself must enforce access.
    mock_file_store.read_file_record.assert_not_called()
    assert (archive, sha) == (ARCHIVE, None)
    assert provider.downloads == [SHA]


def test_file_store_failure_falls_back_to_download(
    mock_file_store: MagicMock,
) -> None:
    mock_file_store.read_file_record.side_effect = RuntimeError("store down")
    mock_file_store.save_file.side_effect = RuntimeError("store down")

    archive, sha, _ = _fetch(_provider())

    assert (archive, sha) == (ARCHIVE, SHA)


def test_download_error_propagates_and_cleans_up(mock_file_store: MagicMock) -> None:
    provider = _provider()
    with pytest.raises(OnyxError):
        with open_repo_archive(provider, TEST_REPO, None, max_size_bytes=4, timeout=30):
            pass
    mock_file_store.save_file.assert_not_called()
