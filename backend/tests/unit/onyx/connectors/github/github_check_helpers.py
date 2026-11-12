"""Token, gateway and config builders that the GitHub capability check tests share."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.github.models import (
    GitHubGitTree,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
    GitHubTokenInfo,
    GitHubTokenKind,
    GitHubTreeEntry,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubSourceOperations,
)
from tests.unit.onyx.connectors.github.conftest import raw_repository

_CLASSIC = GitHubTokenInfo(
    login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["repo", "read:org"]
)
CLASSIC_PUBLIC_ONLY_TOKEN = GitHubTokenInfo(
    login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["read:org"]
)
FINE_GRAINED_TOKEN = GitHubTokenInfo(login="octocat", kind=GitHubTokenKind.FINE_GRAINED)


def make_repo(name: str = "docs") -> GitHubRepository:
    return GitHubRepository.from_raw(raw_repository(name=name, owner="acme"))


def _pr(number: int = 1) -> GitHubPullRequest:
    return GitHubPullRequest(
        number=number,
        title="PR",
        state="open",
        html_url=f"https://github.com/acme/docs/pull/{number}",
    )


def make_issue(number: int, is_pull_request: bool = False) -> GitHubIssue:
    return GitHubIssue(
        number=number,
        title="Issue",
        state="open",
        html_url=f"https://github.com/acme/docs/issues/{number}",
        updated_at="2024-01-01T00:00:00Z",
        is_pull_request=is_pull_request,
        repo_full_name="acme/docs",
    )


def healthy_gateway() -> MagicMock:
    """An organization ``acme`` with one repository ``docs`` that has a pull
    request, an issue and a README, read with a classic token."""
    gateway: MagicMock = create_autospec(GitHubSourceOperations, instance=True)
    gateway.get_token_info.return_value = _CLASSIC
    gateway.list_organization_repositories.return_value = [make_repo()]
    gateway.list_user_repositories.return_value = []
    gateway.get_repository.side_effect = lambda *, owner, name: make_repo(name)  # noqa: ARG005
    gateway.list_pull_requests.return_value = [_pr()]
    gateway.list_issues.return_value = [make_issue(1)]
    gateway.get_git_tree.return_value = GitHubGitTree(
        entries=[
            GitHubTreeEntry(path="src/main.py", type="blob", size=10),
            GitHubTreeEntry(path="README.md", type="blob", size=10),
        ]
    )
    return gateway


def form_config(**overrides: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty text fields."""
    return {
        "repo_owner": "acme",
        "repositories": "",
        "include_prs": True,
        "include_issues": True,
        "include_files": True,
        "branch": "",
        **overrides,
    }


def api_error(
    status: int,
    github_message: str | None = None,
    **kwargs: Any,
) -> GitHubApiError:
    return GitHubApiError(
        f"{status} {github_message}",
        status_code=status,
        github_message=github_message,
        **kwargs,
    )
