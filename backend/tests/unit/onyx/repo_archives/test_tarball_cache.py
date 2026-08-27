from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import FileOrigin
from onyx.db.file_record import FileRecordNotFoundError
from onyx.error_handling.exceptions import OnyxError
from onyx.repo_archives import tarball_cache
from onyx.repo_archives.models import RepoRef
from onyx.repo_archives.tarball_cache import (
    _file_id,
    open_repo_archive,
    open_revision_archive,
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
    # The real store filters in SQL (LIKE 'prefix%'); tests set `records` and
    # the fake applies the same filter, so a listing can never return an id
    # the production query would have excluded.
    store.records = []
    store.list_files_by_prefix.side_effect = lambda prefix: [
        r for r in store.records if r.file_id.startswith(prefix)
    ]
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


def _record(file_id: str) -> MagicMock:
    record = MagicMock()
    record.file_id = file_id
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


def test_cached_object_larger_than_its_record_is_a_miss(
    mock_file_store: MagicMock,
) -> None:
    """The size check is on the record, so the transfer has to be bounded by
    it for the caller's cap to mean anything."""
    _cached(mock_file_store)
    mock_file_store.read_file.return_value = BytesIO(ARCHIVE + b"x" * MAX_BYTES)
    provider = _provider()

    archive, _, _ = _fetch(provider)

    assert archive == ARCHIVE
    assert provider.downloads == [SHA]


def test_new_sha_evicts_previous_entries(
    mock_file_store: MagicMock, mock_delete_files: MagicMock
) -> None:
    old_record = _record(_file_id(revision("b" * 40)))
    other_repo = RepoRef(provider="test", host="test.local", owner="other", name="r")
    other_record = _record(_file_id(revision("c" * 40, other_repo)))
    mock_file_store.records = [old_record, other_record]

    _fetch(_provider())

    assert mock_delete_files.call_args.args[0] == [old_record.file_id]
    mock_file_store.save_file.assert_called_once()


def test_write_path_lists_only_this_repos_prefix(mock_file_store: MagicMock) -> None:
    """The write path must never scan the feature-wide prefix: that resolves
    to an unindexed LIKE over every file_record in the tenant."""
    _fetch(_provider())

    listed = [
        call.args[0] for call in mock_file_store.list_files_by_prefix.call_args_list
    ]
    assert listed == [f"{tarball_cache._FILE_ID_PREFIX}{TEST_REPO.key_prefix}"]


def test_nested_owner_does_not_evict_the_other_repo(
    mock_file_store: MagicMock, mock_delete_files: MagicMock
) -> None:
    """`owner` is a namespace path, so repo(owner="group", name="sub") and
    repo(owner="group/sub", name="x") share a key prefix. Caching one must
    not evict the other."""
    outer = RepoRef(provider="test", host="test.local", owner="group", name="sub")
    inner = RepoRef(provider="test", host="test.local", owner="group/sub", name="x")
    inner_record = _record(_file_id(revision("f" * 40, inner)))
    outer_record = _record(_file_id(revision("b" * 40, outer)))
    mock_file_store.records = [inner_record, outer_record]

    provider = _provider()
    with open_repo_archive(provider, outer, None, max_size_bytes=MAX_BYTES, timeout=30):
        pass

    # The nested repo's entry survives; only the outer repo's own older SHA goes.
    assert mock_delete_files.call_args.args[0] == [outer_record.file_id]
