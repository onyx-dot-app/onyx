"""
Tests verifying that GithubConnector implements SlimConnector and SlimConnectorWithPermSync
correctly, and that pruning uses the cheap slim path (no lazy loading).
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from unittest.mock import PropertyMock

import pytest

from onyx.access.models import ExternalAccess
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import SlimDocument


def _make_pr(html_url: str) -> MagicMock:
    pr = MagicMock()
    pr.html_url = html_url
    pr.pull_request = None
    # commits and changed_files should never be accessed during slim retrieval
    type(pr).commits = PropertyMock(side_effect=AssertionError("lazy load triggered"))
    type(pr).changed_files = PropertyMock(
        side_effect=AssertionError("lazy load triggered")
    )
    return pr


def _make_issue(html_url: str) -> MagicMock:
    issue = MagicMock()
    issue.html_url = html_url
    issue.pull_request = None
    return issue


def _make_connector(include_issues: bool = False) -> GithubConnector:
    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=True,
        include_issues=include_issues,
    )
    connector.github_client = MagicMock()
    return connector


@pytest.fixture(autouse=True)
def patch_deserialize_repository(mock_repo: MagicMock) -> Generator[None, None, None]:
    with patch(
        "onyx.connectors.github.connector.deserialize_repository",
        return_value=mock_repo,
    ):
        yield


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.name = "test-repo"
    repo.id = 123
    repo.raw_headers = {"x-github-request-id": "test"}
    repo.raw_data = {"id": 123, "name": "test-repo", "full_name": "test-org/test-repo"}
    prs = [
        _make_pr(f"https://github.com/test-org/test-repo/pull/{i}") for i in range(1, 4)
    ]
    mock_paginated = MagicMock()
    mock_paginated.get_page.side_effect = lambda page: prs if page == 0 else []
    repo.get_pulls.return_value = mock_paginated
    return repo


def test_github_connector_implements_slim_connector() -> None:
    connector = _make_connector()
    assert isinstance(connector, SlimConnector)


def test_github_connector_implements_slim_connector_with_perm_sync() -> None:
    connector = _make_connector()
    assert isinstance(connector, SlimConnectorWithPermSync)


def test_retrieve_all_slim_docs_returns_pr_urls(mock_repo: MagicMock) -> None:
    connector = _make_connector()
    with patch.object(connector, "fetch_configured_repos", return_value=[mock_repo]):
        batches = list(connector.retrieve_all_slim_docs())

    all_docs = [doc for batch in batches for doc in batch]
    assert len(all_docs) == 3
    assert all(isinstance(doc, SlimDocument) for doc in all_docs)
    assert {doc.id for doc in all_docs if isinstance(doc, SlimDocument)} == {
        "https://github.com/test-org/test-repo/pull/1",
        "https://github.com/test-org/test-repo/pull/2",
        "https://github.com/test-org/test-repo/pull/3",
    }


def test_retrieve_all_slim_docs_has_no_external_access(mock_repo: MagicMock) -> None:
    """Pruning does not need permissions — external_access should be None."""
    connector = _make_connector()
    with patch.object(connector, "fetch_configured_repos", return_value=[mock_repo]):
        batches = list(connector.retrieve_all_slim_docs())

    all_docs = [doc for batch in batches for doc in batch]
    assert all(doc.external_access is None for doc in all_docs)


def test_retrieve_all_slim_docs_perm_sync_populates_external_access(
    mock_repo: MagicMock,
) -> None:
    connector = _make_connector()
    mock_access = MagicMock(spec=ExternalAccess)

    with patch.object(connector, "fetch_configured_repos", return_value=[mock_repo]):
        with patch(
            "onyx.connectors.github.connector.get_external_access_permission",
            return_value=mock_access,
        ) as mock_perm:
            batches = list(connector.retrieve_all_slim_docs_perm_sync())

    # permission fetched at least once per repo (once per page in checkpoint-based flow)
    mock_perm.assert_called_with(mock_repo, connector.github_client)

    all_docs = [doc for batch in batches for doc in batch]
    assert all(doc.external_access is mock_access for doc in all_docs)


def test_retrieve_all_slim_docs_skips_pr_issues(mock_repo: MagicMock) -> None:
    """Issues that are actually PRs should be skipped when include_issues=True."""
    connector = _make_connector(include_issues=True)

    pr_issue = MagicMock()
    pr_issue.html_url = "https://github.com/test-org/test-repo/pull/99"
    pr_issue.pull_request = MagicMock()  # non-None means it's a PR

    real_issue = _make_issue("https://github.com/test-org/test-repo/issues/1")
    issues = [pr_issue, real_issue]
    mock_issues_paginated = MagicMock()
    mock_issues_paginated.get_page.side_effect = lambda page: (
        issues if page == 0 else []
    )
    mock_repo.get_issues.return_value = mock_issues_paginated

    with patch.object(connector, "fetch_configured_repos", return_value=[mock_repo]):
        batches = list(connector.retrieve_all_slim_docs())

    issue_ids = {
        doc.id
        for batch in batches
        for doc in batch
        if isinstance(doc, SlimDocument) and "issues" in doc.id
    }
    assert issue_ids == {"https://github.com/test-org/test-repo/issues/1"}


def test_pruning_routes_to_slim_connector_path(mock_repo: MagicMock) -> None:
    """extract_ids_from_runnable_connector must use SlimConnector, not CheckpointedConnector."""
    connector = _make_connector()

    with patch.object(connector, "fetch_configured_repos", return_value=[mock_repo]):
        # If the CheckpointedConnector fallback were used instead, it would call
        # load_from_checkpoint which hits _convert_pr_to_document and lazy loads.
        # We verify the slim path is taken by checking load_from_checkpoint is NOT called.
        with patch.object(connector, "load_from_checkpoint") as mock_load:
            result = extract_ids_from_runnable_connector(connector)
            mock_load.assert_not_called()

    assert len(result.raw_id_to_parent) == 3
    assert "https://github.com/test-org/test-repo/pull/1" in result.raw_id_to_parent
