import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.models import CodeSection, Document
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.unit.onyx.connectors.github.conftest import make_mock_repo
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.utils.repo_archives import (
    FakeArchiveProvider,
    isolate_repo_archive_caches,
    make_repo_tarball,
)

SHA = "a" * 40
FILES = {
    "src/main.py": b"def main():\n    return 1\n",
    "README.md": b"# Hello\n",
}


@pytest.fixture(autouse=True)
def isolated_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    return isolate_repo_archive_caches(monkeypatch, tmp_path)


def _patch_provider(provider: FakeArchiveProvider) -> Any:
    provider_cls = MagicMock()
    provider_cls.from_token.return_value = provider
    return patch(
        "onyx.connectors.github.connector.GitHubArchiveProvider",
        provider_cls,
    )


def test_connector_files_stage_uses_snapshot_not_api(
    mock_github_client: MagicMock,
) -> None:
    from onyx.connectors.github.models import SerializedRepository

    mock_repo = make_mock_repo()
    mock_github_client.get_repo.return_value = mock_repo

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_files=True,
        include_code_files=True,
    )
    connector.github_client = mock_github_client
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
        assert connector._ensure_snapshot(make_mock_repo()) is None
    assert provider.downloads == []


def test_connector_falls_back_to_api_when_download_fails() -> None:
    connector = GithubConnector(repo_owner="o", repositories="r")
    provider = FakeArchiveProvider(archives={SHA: b"x" * 100}, refs={"main": SHA})
    with (
        _patch_provider(provider),
        patch("onyx.connectors.github.connector.REPO_ARCHIVE_MAX_BYTES", 10),
    ):
        assert connector._ensure_snapshot(make_mock_repo()) is None
