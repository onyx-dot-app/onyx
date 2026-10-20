"""The GitHub targeted reindex reads each failed pull request, issue or file
again from its web URL and keys every outcome on that same URL."""

from collections.abc import Callable
from unittest.mock import MagicMock

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import (
    GitHubFileContent,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
)
from onyx.connectors.models import ConnectorFailure, Document
from tests.utils.reindex_targets import synthetic_failure


def test_reindex_reads_pull_requests_issues_and_files_by_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
    create_issue: Callable[..., GitHubIssue],
) -> None:
    connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.get_file_content.return_value = GitHubFileContent(
        content=b"# readme", encoding="base64"
    )
    pr = create_pr(number=7)
    issue = create_issue(number=3)
    file_url = "https://github.com/test-org/test-repo/blob/main/docs/README.md"

    outputs = list(
        connector.reindex(
            [
                synthetic_failure(pr.html_url, pr.html_url),
                synthetic_failure(issue.html_url, issue.html_url),
                synthetic_failure(file_url, file_url),
            ]
        )
    )

    documents = [o for o in outputs if isinstance(o, Document)]
    assert len(documents) == len(outputs) == 3
    assert [d.id for d in documents] == [pr.html_url, issue.html_url, file_url]
    mock_source_operations.get_repository.assert_called_once_with(
        owner="test-org", name="test-repo"
    )
    mock_source_operations.get_pull_request.assert_called_once_with(
        repo_full_name="test-org/test-repo", number=7
    )
    mock_source_operations.get_issue.assert_called_once_with(
        repo_full_name="test-org/test-repo", number=3
    )
    mock_source_operations.get_file_content.assert_called_once_with(
        repo_full_name="test-org/test-repo", path="docs/README.md", ref="main"
    )


def test_reindex_keys_every_failure_on_the_target_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    connector = build_github_connector(branch="release")
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.get_pull_request.side_effect = RuntimeError("gone")
    missing_pr = "https://github.com/test-org/test-repo/pull/404"
    other_branch_file = "https://github.com/test-org/test-repo/blob/main/a.md"
    not_github = "https://example.com/not/a/document"

    outputs = list(
        connector.reindex(
            [
                synthetic_failure(missing_pr, missing_pr),
                synthetic_failure(other_branch_file, other_branch_file),
                synthetic_failure(not_github, not_github),
            ]
        )
    )

    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == len(outputs) == 3
    assert [f.failed_document.document_id for f in failures if f.failed_document] == [
        missing_pr,
        other_branch_file,
        not_github,
    ]
    assert "gone" in failures[0].failure_message
    assert "release" in failures[1].failure_message
    mock_source_operations.get_file_content.assert_not_called()
