"""GithubConnector.reindex applies the crawl's filters to a fetch by id."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.github.connector import (
    GITHUB_MAX_FILE_SIZE_BYTES,
    GithubConnector,
)
from onyx.connectors.github.models import (
    GitHubFileContent,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
)

_REPO_URL = "https://github.com/test-org/test-repo"


def _failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id, document_link=doc_id),
            failure_message="synthetic",
        )
        for doc_id in doc_ids
    ]


def _run(
    connector: GithubConnector, doc_ids: list[str]
) -> tuple[list[Document], list[str]]:
    results: list[Document | ConnectorFailure | HierarchyNode] = list(
        connector.reindex(_failures(doc_ids))
    )
    docs = [r for r in results if isinstance(r, Document)]
    failed_ids = [
        r.failed_document.document_id
        for r in results
        if isinstance(r, ConnectorFailure) and r.failed_document
    ]
    assert len(docs) + len(failed_ids) == len(results)
    return docs, failed_ids


def test_reindex_pull_request_and_issue(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
    create_issue: Callable[..., GitHubIssue],
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    pr = create_pr(number=3)
    issue = create_issue(number=4)

    docs, failed_ids = _run(build_github_connector(), [pr.html_url, issue.html_url])

    assert failed_ids == []
    assert sorted(d.id for d in docs) == sorted([pr.html_url, issue.html_url])
    # One repository read serves both targets.
    assert mock_source_operations.get_repository.call_count == 1


def test_reindex_skips_state_the_filter_excludes(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
    create_issue: Callable[..., GitHubIssue],
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    pr = create_pr(number=3, state="closed")
    issue = create_issue(number=4, state="closed")
    connector = build_github_connector()
    connector.state_filter = "open"

    docs, failed_ids = _run(connector, [pr.html_url, issue.html_url])

    assert docs == []
    assert sorted(failed_ids) == sorted([pr.html_url, issue.html_url])


def test_reindex_skips_pull_request_read_as_issue(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_issue: Callable[..., GitHubIssue],
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    issue = create_issue(number=5, is_pull_request=True)

    docs, failed_ids = _run(build_github_connector(), [issue.html_url])

    assert docs == []
    assert failed_ids == [issue.html_url]


def test_reindex_skips_disabled_doc_types(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    targets = [
        f"{_REPO_URL}/pull/1",
        f"{_REPO_URL}/issues/2",
        f"{_REPO_URL}/blob/main/README.md",
    ]
    connector = build_github_connector(
        include_prs=False, include_issues=False, include_files=False
    )

    docs, failed_ids = _run(connector, targets)

    assert docs == []
    assert sorted(failed_ids) == sorted(targets)
    mock_source_operations.get_repository.assert_not_called()


def test_reindex_skips_repos_outside_configured_scope(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    targets = [
        "https://github.com/other-org/test-repo/pull/1",
        "https://github.com/test-org/other-repo/pull/1",
    ]

    docs, failed_ids = _run(build_github_connector(), targets)

    assert docs == []
    assert sorted(failed_ids) == sorted(targets)
    mock_source_operations.get_repository.assert_not_called()


def test_reindex_skips_private_user_repo_without_repo_list(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    # The crawl lists a user's repositories through an endpoint that returns
    # only public ones.
    mock_source_operations.get_repository.return_value = create_repo().model_copy(
        update={"private": True, "visibility": "private", "organization": None}
    )
    pr = create_pr(number=3)

    docs, failed_ids = _run(build_github_connector(repositories=""), [pr.html_url])

    assert docs == []
    assert failed_ids == [pr.html_url]
    mock_source_operations.get_pull_request.assert_not_called()


def test_reindex_files_apply_the_crawl_file_filters(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    contents = {
        "docs/guide.md": b"# Guide",
        "docs/huge.md": b"x" * (GITHUB_MAX_FILE_SIZE_BYTES + 1),
    }
    mock_source_operations.get_file_content.side_effect = (
        lambda *, repo_full_name, path, ref: _file_content(  # noqa: ARG005
            path, contents[path]
        )
    )
    good = f"{_REPO_URL}/blob/main/docs/guide.md"
    excluded = [
        f"{_REPO_URL}/blob/main/docs/huge.md",
        f"{_REPO_URL}/blob/main/node_modules/pkg/README.md",
        f"{_REPO_URL}/blob/main/src/main.py",
        # Not the indexed branch.
        f"{_REPO_URL}/blob/feature/docs/guide.md",
    ]
    connector = build_github_connector(include_files=True)

    docs, failed_ids = _run(connector, [good, *excluded])

    assert [d.id for d in docs] == [good]
    assert sorted(failed_ids) == sorted(excluded)


def _file_content(
    path: str, content: bytes, repo_url: str = _REPO_URL
) -> GitHubFileContent:
    return GitHubFileContent(
        content=content,
        encoding="base64",
        path=path,
        html_url=f"{repo_url}/blob/main/{path}",
    )


@pytest.mark.parametrize(
    "doc_id",
    [
        # Dot segments that the HTTP client resolves into another repository.
        f"{_REPO_URL}/blob/main/x/../../../../test-org/private-repo/contents/README.md",
        f"{_REPO_URL}/blob/main/./README.md",
        # Escaped dot segments.
        f"{_REPO_URL}/blob/main/x/%2e%2e/%2E%2E/README.md",
        # An escaped denylisted segment.
        f"{_REPO_URL}/blob/main/node%5Fmodules/pkg/README.md",
        # Empty segments.
        f"{_REPO_URL}/blob/main/docs//README.md",
        f"{_REPO_URL}/blob/main/docs/README.md/",
        # Backslash and control characters.
        f"{_REPO_URL}/blob/main/docs\\..\\README.md",
        f"{_REPO_URL}/blob/main/docs/READ\nME.md",
        # Unsafe owner or repository names.
        "https://github.com/test-org/../private-repo/pull/1",
        "https://github.com/test-org/test%2Drepo/issues/1",
    ],
)
def test_reindex_refuses_unsafe_paths_without_fetching(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    doc_id: str,
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    connector = build_github_connector(include_files=True)

    docs, failed_ids = _run(connector, [doc_id])

    assert docs == []
    assert failed_ids == [doc_id]
    mock_source_operations.get_file_content.assert_not_called()
    mock_source_operations.get_pull_request.assert_not_called()
    mock_source_operations.get_issue.assert_not_called()


def test_reindex_keeps_literal_percent_in_file_name(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    # The crawl writes tree paths unescaped, so a git path may hold '%'.
    mock_source_operations.get_repository.return_value = create_repo()
    path = "docs/100%.md"
    mock_source_operations.get_file_content.return_value = _file_content(path, b"x")
    doc_id = f"{_REPO_URL}/blob/main/{path}"

    docs, failed_ids = _run(build_github_connector(include_files=True), [doc_id])

    assert failed_ids == []
    assert [d.id for d in docs] == [doc_id]


@pytest.mark.parametrize(
    "returned",
    [
        _file_content("other/README.md", b"x"),
        _file_content(
            "docs/README.md", b"x", repo_url="https://github.com/test-org/private"
        ),
    ],
)
def test_reindex_refuses_content_from_another_location(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    returned: GitHubFileContent,
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.get_file_content.return_value = returned
    doc_id = f"{_REPO_URL}/blob/main/docs/README.md"

    docs, failed_ids = _run(build_github_connector(include_files=True), [doc_id])

    assert docs == []
    assert failed_ids == [doc_id]


def test_reindex_retries_rate_limit(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    mock_source_operations.get_repository.side_effect = [
        GitHubRateLimitError("limited", status_code=403, secondary=False),
        create_repo(),
    ]
    pr = create_pr(number=3)

    with patch(
        "onyx.connectors.github.connector.sleep_after_rate_limit_exception"
    ) as sleep:
        docs, failed_ids = _run(build_github_connector(), [pr.html_url])

    assert sleep.call_count == 1
    assert failed_ids == []
    assert [d.id for d in docs] == [pr.html_url]


def test_reindex_missing_target_does_not_stop_the_rest(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    mock_source_operations.get_repository.return_value = create_repo()
    pr = create_pr(number=3)
    missing = f"{_REPO_URL}/pull/404"

    def get_pull_request(
        *,
        repo_full_name: str,  # noqa: ARG001
        number: int,
    ) -> GitHubPullRequest:
        if number != pr.number:
            raise GitHubApiError("missing", status_code=404)
        return pr

    mock_source_operations.get_pull_request.side_effect = get_pull_request

    docs, failed_ids = _run(build_github_connector(), [missing, pr.html_url])

    assert failed_ids == [missing]
    assert [d.id for d in docs] == [pr.html_url]


def test_reindex_raises_on_rejected_credential(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_repository.side_effect = GitHubApiError(
        "bad credentials", status_code=401
    )

    with pytest.raises(GitHubApiError):
        _run(build_github_connector(), [f"{_REPO_URL}/pull/1"])
