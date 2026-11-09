"""
Tests verifying that GithubConnector implements SlimConnector and SlimConnectorWithPermSync
correctly, and that pruning uses the cheap slim path (no per-item reads).
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import GitHubPullRequest, GitHubRepository
from onyx.connectors.interfaces import SlimConnector, SlimConnectorWithPermSync
from onyx.connectors.models import SlimDocument


@pytest.fixture
def mock_repo(
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> GitHubRepository:
    repo = create_repo(repo_id=123)
    mock_source_operations.get_repository.return_value = repo
    prs = [create_pr(number=i) for i in range(1, 4)]
    mock_source_operations.list_pull_requests.side_effect = (
        lambda *, repo_full_name, state, page: prs if page == 0 else []  # noqa: ARG005
    )
    return repo


@pytest.fixture
def make_connector(
    build_github_connector: Callable[..., GithubConnector],
) -> Callable[..., GithubConnector]:
    def _make(include_issues: bool = False) -> GithubConnector:
        return build_github_connector(include_prs=True, include_issues=include_issues)

    return _make


def test_github_connector_implements_slim_connector(
    make_connector: Callable[..., GithubConnector],
) -> None:
    assert isinstance(make_connector(), SlimConnector)


def test_github_connector_implements_slim_connector_with_perm_sync(
    make_connector: Callable[..., GithubConnector],
) -> None:
    assert isinstance(make_connector(), SlimConnectorWithPermSync)


@pytest.mark.usefixtures("mock_repo")
def test_retrieve_all_slim_docs_returns_pr_urls(
    make_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    connector = make_connector()
    batches = list(connector.retrieve_all_slim_docs())

    all_docs = [doc for batch in batches for doc in batch]
    assert len(all_docs) == 3
    assert all(isinstance(doc, SlimDocument) for doc in all_docs)
    assert {doc.id for doc in all_docs if isinstance(doc, SlimDocument)} == {
        "https://github.com/test-org/test-repo/pull/1",
        "https://github.com/test-org/test-repo/pull/2",
        "https://github.com/test-org/test-repo/pull/3",
    }
    # Slim documents need no details, so no pull request or user is read.
    mock_source_operations.get_pull_request.assert_not_called()
    mock_source_operations.get_user.assert_not_called()


@pytest.mark.usefixtures("mock_repo")
def test_retrieve_all_slim_docs_has_no_external_access(
    make_connector: Callable[..., GithubConnector],
) -> None:
    """Pruning does not need permissions — external_access should be None."""
    connector = make_connector()
    batches = list(connector.retrieve_all_slim_docs())

    all_docs = [doc for batch in batches for doc in batch]
    assert all(doc.external_access is None for doc in all_docs)


def test_retrieve_all_slim_docs_perm_sync_populates_external_access(
    make_connector: Callable[..., GithubConnector],
    mock_repo: GitHubRepository,
) -> None:
    connector = make_connector()
    mock_access = MagicMock(spec=ExternalAccess)

    with patch(
        "onyx.connectors.github.connector.get_external_access_permission",
        return_value=mock_access,
    ) as mock_perm:
        batches = list(connector.retrieve_all_slim_docs_perm_sync())

    # permission fetched at least once per repo (once per page in checkpoint-based flow)
    mock_perm.assert_called_with(mock_repo)

    all_docs = [doc for batch in batches for doc in batch]
    assert all(doc.external_access is mock_access for doc in all_docs)


@pytest.mark.usefixtures("mock_repo")
def test_retrieve_all_slim_docs_skips_pr_issues(
    make_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_issue: Callable[..., Any],
) -> None:
    """Issues that are actually PRs should be skipped when include_issues=True."""
    connector = make_connector(include_issues=True)

    issues = [
        create_issue(number=99, is_pull_request=True),
        create_issue(number=1),
    ]
    mock_source_operations.list_issues.side_effect = (
        lambda *, repo_full_name, state, page: issues if page == 0 else []  # noqa: ARG005
    )

    batches = list(connector.retrieve_all_slim_docs())

    issue_ids = {
        doc.id
        for batch in batches
        for doc in batch
        if isinstance(doc, SlimDocument) and "issues" in doc.id
    }
    assert issue_ids == {"https://github.com/test-org/test-repo/issues/1"}
    mock_source_operations.get_issue.assert_not_called()


@pytest.mark.usefixtures("mock_repo")
def test_pruning_routes_to_slim_connector_path(
    make_connector: Callable[..., GithubConnector],
) -> None:
    """extract_ids_from_runnable_connector must use SlimConnector, not CheckpointedConnector."""
    connector = make_connector()

    # If the CheckpointedConnector fallback were used instead, it would call
    # load_from_checkpoint, which reads every pull request on its own.
    # We verify the slim path is taken by checking load_from_checkpoint is NOT called.
    with patch.object(connector, "load_from_checkpoint") as mock_load:
        result = extract_ids_from_runnable_connector(connector)
        mock_load.assert_not_called()

    assert len(result.raw_id_to_parent) == 3
    assert "https://github.com/test-org/test-repo/pull/1" in result.raw_id_to_parent
