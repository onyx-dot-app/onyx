from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import (
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
    GitHubUser,
)
from onyx.connectors.github.source_operations import GitHubSourceOperations

_RATE_LIMIT_RESET = datetime(2023, 1, 1, tzinfo=timezone.utc)


def raw_repository(
    name: str = "test-repo",
    repo_id: int = 1,
    owner: str = "test-org",
    **overrides: Any,
) -> dict[str, Any]:
    """A repository as the GitHub REST API returns it."""
    return {
        "id": repo_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "html_url": f"https://github.com/{owner}/{name}",
        "private": False,
        "visibility": "public",
        "default_branch": "main",
        "pushed_at": "2023-01-01T00:00:00Z",
        "owner": {"login": owner, "id": 100, "type": "Organization"},
        **overrides,
    }


class KnownItems:
    """The pull requests and issues a test created, so the fake gateway can
    read them one by one."""

    def __init__(self) -> None:
        self.pull_requests: dict[tuple[str, int], GitHubPullRequest] = {}
        self.issues: dict[tuple[str, int], GitHubIssue] = {}


@pytest.fixture
def known_items() -> KnownItems:
    return KnownItems()


@pytest.fixture
def mock_source_operations(known_items: KnownItems) -> MagicMock:
    """A fake gateway. ``get_pull_request`` and ``get_issue`` return the
    created item, marked as detailed."""
    gateway: MagicMock = create_autospec(GitHubSourceOperations, instance=True)
    gateway.get_rate_limit_reset.return_value = _RATE_LIMIT_RESET
    gateway.list_pull_requests.return_value = []
    gateway.list_issues.return_value = []
    gateway.iter_pull_requests_by_cursor.side_effect = lambda **_kwargs: iter([])
    gateway.iter_issues_by_cursor.side_effect = lambda **_kwargs: iter([])
    gateway.get_user.side_effect = lambda *, login: GitHubUser(login=login)
    gateway.get_pull_request.side_effect = lambda *, repo_full_name, number: (
        known_items.pull_requests[(repo_full_name, number)].model_copy(
            update={"detailed": True}
        )
    )
    gateway.get_issue.side_effect = lambda *, repo_full_name, number: (
        known_items.issues[(repo_full_name, number)].model_copy(
            update={"detailed": True}
        )
    )
    return gateway


@pytest.fixture
def create_repo() -> Callable[..., GitHubRepository]:
    def _create_repo(
        name: str = "test-repo", repo_id: int = 1, **overrides: Any
    ) -> GitHubRepository:
        return GitHubRepository.from_raw(
            raw_repository(name=name, repo_id=repo_id, **overrides)
        )

    return _create_repo


@pytest.fixture
def create_pr(known_items: KnownItems) -> Callable[..., GitHubPullRequest]:
    def _create_pr(
        number: int = 1,
        title: str = "Test PR",
        body: str = "Test Description",
        state: str = "open",
        merged: bool = False,
        updated_at: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
        html_url: str | None = None,
        repo_full_name: str = "test-org/test-repo",
    ) -> GitHubPullRequest:
        pull_request = GitHubPullRequest(
            number=number,
            title=title,
            body=body,
            state=state,
            html_url=(
                html_url
                if html_url is not None
                else f"https://github.com/{repo_full_name}/pull/{number}"
            ),
            created_at=updated_at,
            updated_at=updated_at,
            base_repo_full_name=repo_full_name,
            merged=merged,
        )
        known_items.pull_requests[(repo_full_name, number)] = pull_request
        return pull_request

    return _create_pr


@pytest.fixture
def create_issue(known_items: KnownItems) -> Callable[..., GitHubIssue]:
    def _create_issue(
        number: int = 1,
        title: str = "Test Issue",
        body: str = "Test Description",
        state: str = "open",
        updated_at: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
        is_pull_request: bool = False,
    ) -> GitHubIssue:
        issue = GitHubIssue(
            number=number,
            title=title,
            body=body,
            state=state,
            html_url=f"https://github.com/test-org/test-repo/issues/{number}",
            created_at=updated_at,
            updated_at=updated_at,
            is_pull_request=is_pull_request,
            repo_full_name="test-org/test-repo",
        )
        known_items.issues[(issue.repo_full_name, number)] = issue
        return issue

    return _create_issue


@pytest.fixture
def build_github_connector(
    mock_source_operations: MagicMock,
) -> Callable[..., GithubConnector]:
    def _build(
        repo_owner: str = "test-org",
        repositories: str = "test-repo",
        include_prs: bool = True,
        include_issues: bool = True,
        include_files: bool = False,
        branch: str | None = None,
    ) -> GithubConnector:
        connector = GithubConnector(
            repo_owner=repo_owner,
            repositories=repositories,
            include_prs=include_prs,
            include_issues=include_issues,
            include_files=include_files,
            branch=branch,
        )
        connector._source_operations = mock_source_operations
        return connector

    return _build
