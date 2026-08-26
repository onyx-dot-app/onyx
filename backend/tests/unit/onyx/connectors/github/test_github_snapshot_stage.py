import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.models import CodeSection, Document
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.repo_archives import snapshot
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.utils.repo_archives import FakeArchiveProvider, make_repo_tarball

SHA = "a" * 40
FILES = {
    "src/main.py": b"def main():\n    return 1\n",
    "README.md": b"# Hello\n",
}


@pytest.fixture(autouse=True)
def isolated_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(snapshot, "_CACHE_ROOT", tmp_path / "snapshot_cache")
    store = MagicMock()
    store.has_file.return_value = False
    store.list_files_by_prefix.return_value = []
    with patch(
        "onyx.repo_archives.tarball_cache.get_default_file_store", return_value=store
    ):
        yield


def _patch_provider(provider: FakeArchiveProvider):
    return patch(
        "onyx.connectors.github.connector.GitHubArchiveProvider",
        return_value=provider,
    )


def _mock_github_repo() -> MagicMock:
    repo = MagicMock()
    repo.name = "test-repo"
    repo.id = 1
    repo.full_name = "test-org/test-repo"
    repo.html_url = "https://github.com/test-org/test-repo"
    repo.default_branch = "main"
    repo.pushed_at = datetime(2023, 1, 1)
    repo.configure_mock(
        raw_headers={"status": "200 OK"},
        raw_data={"id": 1, "full_name": "test-org/test-repo"},
    )
    return repo


def test_connector_files_stage_uses_snapshot_not_api() -> None:
    from github import Github
    from github.RateLimit import RateLimit
    from github.Requester import Requester

    from onyx.connectors.github.models import SerializedRepository

    mock_repo = _mock_github_repo()
    mock_client = MagicMock(spec=Github)
    mock_client.get_repo = MagicMock(return_value=mock_repo)
    mock_client.get_rate_limit = MagicMock(return_value=MagicMock(spec=RateLimit))
    mock_client._requester = MagicMock(spec=Requester)

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_files=True,
        include_code_files=True,
    )
    connector.github_client = mock_client
    provider = FakeArchiveProvider(
        archives={SHA: make_repo_tarball(FILES)}, refs={"main": SHA}
    )

    with (
        patch.object(SerializedRepository, "to_Repository", return_value=mock_repo),
        _patch_provider(provider),
    ):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert sorted(d.semantic_identifier for d in docs) == ["README.md", "src/main.py"]

    # The whole file stage ran on ONE archive fetch — zero per-file calls.
    assert provider.downloads == [SHA]
    mock_repo.get_git_tree.assert_not_called()
    mock_repo.get_contents.assert_not_called()
    mock_repo.get_branch.assert_not_called()

    code_doc = next(d for d in docs if d.semantic_identifier == "src/main.py")
    assert isinstance(code_doc.sections[0], CodeSection)
    assert code_doc.metadata["commit_sha"] == SHA


def test_connector_falls_back_to_api_when_resolution_fails() -> None:
    """No resolved SHA, no snapshot: the branch could move under a
    branch-keyed cache."""
    connector = GithubConnector(repo_owner="o", repositories="r")
    provider = FakeArchiveProvider(
        archives={}, resolve_error=OnyxError(OnyxErrorCode.RATE_LIMITED)
    )
    with _patch_provider(provider):
        assert connector._ensure_snapshot(_mock_github_repo()) is None
    assert provider.downloads == []


def test_connector_falls_back_to_api_when_download_fails() -> None:
    connector = GithubConnector(repo_owner="o", repositories="r")
    provider = FakeArchiveProvider(archives={SHA: b"x" * 100}, refs={"main": SHA})
    with (
        _patch_provider(provider),
        patch("onyx.connectors.github.connector.GITHUB_REPO_ARCHIVE_MAX_BYTES", 10),
    ):
        assert connector._ensure_snapshot(_mock_github_repo()) is None
