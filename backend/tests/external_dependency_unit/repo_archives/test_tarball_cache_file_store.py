"""tarball_cache against the real file store: eviction and the upsert
semantics the unit tests can only mock."""

import uuid
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from onyx.file_store.file_store import get_default_file_store
from onyx.repo_archives import tarball_cache
from onyx.repo_archives.models import RepoRef
from onyx.repo_archives.tarball_cache import (
    _file_id,
    open_repo_archive,
)
from tests.utils.repo_archives import FakeArchiveProvider, revision

ARCHIVE = b"tarball-bytes"

pytestmark = pytest.mark.usefixtures(
    "db_session", "tenant_context", "initialize_file_store"
)


def _fetch(repo: RepoRef, sha: str, archive: bytes = ARCHIVE) -> tuple[bytes, int]:
    """(archive bytes served, number of downloads performed)."""
    provider = FakeArchiveProvider(archives={sha: archive}, refs={None: sha})
    with open_repo_archive(
        provider, repo, None, max_size_bytes=10_000, timeout=30
    ) as result:
        assert result.revision == revision(sha, repo)
        return result.path.read_bytes(), len(provider.downloads)


def _cached_ids(repo: RepoRef) -> set[str]:
    prefix = f"{tarball_cache._FILE_ID_PREFIX}{repo.key_prefix}"
    return {r.file_id for r in get_default_file_store().list_files_by_prefix(prefix)}


def _cleanup(repo: RepoRef) -> None:
    store = get_default_file_store()
    for file_id in _cached_ids(repo):
        store.delete_file(file_id, error_on_missing=False)


def _repo(name: str) -> RepoRef:
    return RepoRef(
        provider="test",
        host="test.local",
        owner=f"org-{uuid.uuid4().hex[:8]}",
        name=name,
    )


@pytest.fixture
def repo() -> Iterator[RepoRef]:
    ref = _repo("repo")
    yield ref
    _cleanup(ref)


def test_miss_then_hit_and_new_sha_evicts_old(repo: RepoRef) -> None:
    sha_1, sha_2 = "1" * 40, "2" * 40

    assert _fetch(repo, sha_1) == (ARCHIVE, 1)
    assert _cached_ids(repo) == {_file_id(revision(sha_1, repo))}

    assert _fetch(repo, sha_1) == (ARCHIVE, 0)

    assert _fetch(repo, sha_2, archive=b"newer") == (b"newer", 1)
    assert _cached_ids(repo) == {_file_id(revision(sha_2, repo))}


def test_same_sha_double_write_is_an_upsert(repo: RepoRef) -> None:
    sha = "3" * 40
    file_id = _file_id(revision(sha, repo))
    store = get_default_file_store()

    _fetch(repo, sha)
    # A second writer for the same SHA (the cache read is forced to miss).
    with patch.object(tarball_cache, "_read_cached_archive", return_value=None):
        _fetch(repo, sha, archive=b"second")

    assert _cached_ids(repo) == {file_id}
    with store.read_file(file_id, mode="b") as f:
        assert f.read() == b"second"


def test_underscore_in_a_repo_name_does_not_evict_a_sibling() -> None:
    """ "_" is a LIKE wildcard, so an unescaped eviction prefix for "my_repo"
    also matches "myXrepo" and the two repos evict each other forever."""
    owner = f"org-{uuid.uuid4().hex[:8]}"
    mine = RepoRef(provider="test", host="test.local", owner=owner, name="my_repo")
    sibling = RepoRef(provider="test", host="test.local", owner=owner, name="myXrepo")
    sibling_sha = "4" * 40

    try:
        _fetch(sibling, sibling_sha)
        _fetch(mine, "5" * 40)
        _fetch(mine, "6" * 40)

        assert _cached_ids(sibling) == {_file_id(revision(sibling_sha, sibling))}
    finally:
        _cleanup(mine)
        _cleanup(sibling)
