import time
from collections.abc import Callable, Iterator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.github.connector import GithubConnector, GithubConnectorStage
from onyx.connectors.github.models import (
    GitHubCursorItem,
    GitHubPullRequest,
    GitHubRepository,
    SerializedRepository,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
)
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
    load_everything_from_checkpoint_connector_from_checkpoint,
)

_CURSOR_REQUIRED_MESSAGE = (
    "Pagination with the page parameter is not supported for large datasets. Use cursor"
)


def _api_error(status: int, github_message: str | None = None) -> GitHubApiError:
    return GitHubApiError(
        f"{status} {github_message}", status_code=status, github_message=github_message
    )


def _cursor_items(
    *items: tuple[GitHubPullRequest, str | None],
) -> Iterator[GitHubCursorItem[GitHubPullRequest]]:
    return iter(
        GitHubCursorItem(item=item, next_url=next_url) for item, next_url in items
    )


def _serialized(repo: GitHubRepository) -> SerializedRepository:
    return SerializedRepository(id=repo.id, raw_data=repo.raw_data)


def test_load_from_checkpoint_happy_path(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
    create_issue: Callable[..., Any],
) -> None:
    """Test loading from checkpoint - happy path"""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_pull_requests.side_effect = [
        [create_pr(number=1, title="PR 1"), create_pr(number=2, title="PR 2")],
        [],
    ]
    mock_source_operations.list_issues.side_effect = [
        [
            create_issue(number=1, title="Issue 1"),
            create_issue(number=2, title="Issue 2"),
        ],
        [],
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(github_connector, 0, end_time)

    # Check that we got all documents and final has_more=False
    assert len(outputs) == 4

    repo_batch = outputs[0]
    assert len(repo_batch.items) == 0
    assert repo_batch.next_checkpoint.has_more is True

    # Check first batch (PRs)
    first_batch = outputs[1]
    assert len(first_batch.items) == 2
    assert isinstance(first_batch.items[0], Document)
    assert first_batch.items[0].id == "https://github.com/test-org/test-repo/pull/1"
    assert isinstance(first_batch.items[1], Document)
    assert first_batch.items[1].id == "https://github.com/test-org/test-repo/pull/2"
    assert first_batch.next_checkpoint.curr_page == 1

    # Check second batch (Issues)
    second_batch = outputs[2]
    assert len(second_batch.items) == 2
    assert isinstance(second_batch.items[0], Document)
    assert second_batch.items[0].id == "https://github.com/test-org/test-repo/issues/1"
    assert isinstance(second_batch.items[1], Document)
    assert second_batch.items[1].id == "https://github.com/test-org/test-repo/issues/2"
    assert second_batch.next_checkpoint.has_more

    # Check third batch (finished checkpoint)
    third_batch = outputs[3]
    assert len(third_batch.items) == 0
    assert third_batch.next_checkpoint.has_more is False


def test_pull_requests_are_read_one_by_one_for_their_details(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """A listing leaves out merged, commits and changed files; the connector
    reads each pull request for them, and each author once."""
    github_connector = build_github_connector(include_issues=False)
    mock_source_operations.get_repository.return_value = create_repo()
    first = create_pr(number=1).model_copy(update={"user_login": "octocat"})
    second = create_pr(number=2).model_copy(update={"user_login": "octocat"})
    detailed = {
        1: first.model_copy(update={"detailed": True, "commits": 3}),
        2: second.model_copy(update={"detailed": True, "commits": 4}),
    }
    mock_source_operations.get_pull_request.side_effect = (
        lambda *, repo_full_name, number: detailed[number]  # noqa: ARG005
    )
    mock_source_operations.list_pull_requests.side_effect = [[first, second], []]

    outputs = load_everything_from_checkpoint_connector(
        github_connector, 0, time.time()
    )

    docs = [item for output in outputs for item in output.items]
    assert [cast(Document, doc).metadata["num_commits"] for doc in docs] == ["3", "4"]
    assert mock_source_operations.get_pull_request.call_count == 2
    mock_source_operations.get_user.assert_called_once_with(login="octocat")


def test_load_from_checkpoint_with_rate_limit(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test loading from checkpoint with rate limit handling"""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_pull_requests.side_effect = [
        GitHubRateLimitError("403 rate limited", status_code=403, secondary=False),
        [create_pr()],
        [],
    ]

    end_time = time.time()
    with patch(
        "onyx.connectors.github.connector.sleep_after_rate_limit_exception"
    ) as mock_sleep:
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

        assert mock_sleep.call_count == 1

    # Check that we got the document after rate limit was handled
    assert len(outputs) >= 2
    assert len(outputs[1].items) == 1
    assert isinstance(outputs[1].items[0], Document)
    assert outputs[1].items[0].id == "https://github.com/test-org/test-repo/pull/1"

    assert outputs[-1].next_checkpoint.has_more is False


def test_load_from_checkpoint_with_empty_repo(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    """Test loading from checkpoint with an empty repository"""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(github_connector, 0, end_time)

    # Check that we got no documents
    assert len(outputs) == 2
    assert len(outputs[-1].items) == 0
    assert not outputs[-1].next_checkpoint.has_more


def test_load_from_checkpoint_with_prs_only(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test loading from checkpoint with only PRs enabled"""
    github_connector = build_github_connector(include_issues=False)
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_pull_requests.side_effect = [
        [create_pr(number=1, title="PR 1"), create_pr(number=2, title="PR 2")],
        [],
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(github_connector, 0, end_time)

    # Check that we only got PRs
    assert len(outputs) >= 2
    assert len(outputs[1].items) == 2
    assert all(
        isinstance(doc, Document) and "pull" in doc.id for doc in outputs[1].items
    )
    mock_source_operations.list_issues.assert_not_called()

    assert outputs[-1].next_checkpoint.has_more is False


def test_load_from_checkpoint_with_issues_only(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_issue: Callable[..., Any],
) -> None:
    """Test loading from checkpoint with only issues enabled"""
    github_connector = build_github_connector(include_prs=False)
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_issues.side_effect = [
        [
            create_issue(number=1, title="Issue 1"),
            create_issue(number=2, title="Issue 2"),
        ],
        [],
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(github_connector, 0, end_time)

    # Check that we only got issues
    assert len(outputs) >= 2
    assert len(outputs[1].items) == 2
    assert all(
        isinstance(doc, Document) and "issues" in doc.id for doc in outputs[1].items
    )
    assert outputs[1].next_checkpoint.has_more
    mock_source_operations.list_pull_requests.assert_not_called()

    assert outputs[-1].next_checkpoint.has_more is False


def test_issues_that_are_pull_requests_are_skipped(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_issue: Callable[..., Any],
) -> None:
    """The issues API lists pull requests too; they are not read or
    indexed as issues."""
    github_connector = build_github_connector(include_prs=False)
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_issues.side_effect = [
        [create_issue(number=1), create_issue(number=2, is_pull_request=True)],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(
        github_connector, 0, time.time()
    )

    docs = [item for output in outputs for item in output.items]
    assert [cast(Document, doc).id for doc in docs] == [
        "https://github.com/test-org/test-repo/issues/1"
    ]
    mock_source_operations.get_issue.assert_called_once_with(
        repo_full_name="test-org/test-repo", number=1
    )


@pytest.mark.parametrize(
    "status_code,expected_exception,expected_message",
    [
        (
            401,
            CredentialExpiredError,
            "GitHub credential appears to be invalid or expired",
        ),
        (
            403,
            InsufficientPermissionsError,
            "Your GitHub token does not have sufficient permissions",
        ),
        (
            404,
            ConnectorValidationError,
            "GitHub repository not found",
        ),
    ],
)
def test_validate_connector_settings_errors(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    mock_source_operations.get_repository.side_effect = _api_error(status_code)
    github_connector = build_github_connector()

    with pytest.raises(expected_exception) as excinfo:
        github_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_rate_limit_is_unexpected(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_repository.side_effect = GitHubRateLimitError(
        "403 rate limited", status_code=403, secondary=True
    )

    with pytest.raises(UnexpectedValidationError, match="rate-limits"):
        build_github_connector().validate_connector_settings()


def test_validate_connector_settings_surfaces_typed_error(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    """A typed ConnectorValidationError raised mid-validation propagates
    unchanged, so the connector-setup API surfaces the real reason
    ("Found no repos...") rather than a generic 500."""
    github_connector = build_github_connector(repositories="")

    # No specific repos -> org lookup fails -> fall back to a user that has
    # zero accessible repos.
    mock_source_operations.get_organization.side_effect = _api_error(404)
    mock_source_operations.list_user_repositories.return_value = []

    with pytest.raises(ConnectorValidationError) as excinfo:
        github_connector.validate_connector_settings()
    assert "Found no repos for user" in str(excinfo.value)
    mock_source_operations.list_user_repositories.assert_called_once_with(
        login="test-org", limit=1
    )


def test_validate_connector_settings_names_missing_sso_authorization(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_organization.side_effect = _api_error(
        403,
        "Resource protected by organization SAML enforcement. You must grant "
        "your Personal Access token access to this organization.",
    )

    with pytest.raises(ConnectorValidationError, match="missing authorization"):
        build_github_connector(repositories="").validate_connector_settings()


def test_validate_connector_settings_success(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    """Test successful validation"""
    mock_source_operations.get_repository.return_value = create_repo()
    github_connector = build_github_connector()

    github_connector.validate_connector_settings()
    mock_source_operations.get_repository.assert_called_once_with(
        owner="test-org", name="test-repo"
    )
    mock_source_operations.list_root_contents.assert_called_once_with(
        repo_full_name="test-org/test-repo"
    )


def test_load_from_checkpoint_with_cursor_fallback(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test loading from checkpoint with fallback to cursor-based pagination"""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    mock_source_operations.list_pull_requests.side_effect = _api_error(
        422, _CURSOR_REQUIRED_MESSAGE
    )
    next_url = "https://api.github.com/repos/test-org/test-repo/pulls?cursor=abc123"
    mock_source_operations.iter_pull_requests_by_cursor.side_effect = [
        _cursor_items(
            (create_pr(number=1, title="PR 1"), next_url),
            (create_pr(number=2, title="PR 2"), next_url),
        )
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(github_connector, 0, end_time)

    # Check that we got the documents via cursor-based pagination
    assert len(outputs) >= 2
    assert len(outputs[1].items) == 2
    assert isinstance(outputs[1].items[0], Document)
    assert outputs[1].items[0].id == "https://github.com/test-org/test-repo/pull/1"
    assert isinstance(outputs[1].items[1], Document)
    assert outputs[1].items[1].id == "https://github.com/test-org/test-repo/pull/2"
    mock_source_operations.iter_pull_requests_by_cursor.assert_called_once_with(
        repo_full_name="test-org/test-repo", state="all", cursor_url=None, skip=0
    )

    # The cursor run finished the stage, so the checkpoint is reset
    assert outputs[1].next_checkpoint.cursor_url is None
    assert outputs[1].next_checkpoint.num_retrieved == 0


def test_load_from_checkpoint_resume_cursor_pagination(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test resuming from a checkpoint that was using cursor-based pagination"""
    github_connector = build_github_connector()
    repo = create_repo()

    # Create a checkpoint that was using cursor-based pagination
    checkpoint = github_connector.build_dummy_checkpoint()
    checkpoint.cached_repo_ids = []
    checkpoint.cached_repo = _serialized(repo)
    cursor_url = "https://api.github.com/repos/test-org/test-repo/pulls?cursor=abc123"
    checkpoint.cursor_url = cursor_url
    checkpoint.num_retrieved = 2

    next_url = "https://api.github.com/repos/test-org/test-repo/pulls?cursor=def456"
    mock_source_operations.iter_pull_requests_by_cursor.side_effect = [
        _cursor_items(
            (create_pr(number=3, title="PR 3"), next_url),
            (create_pr(number=4, title="PR 4"), next_url),
        )
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        github_connector, 0, end_time, checkpoint
    )

    # Check that we got the documents via cursor-based pagination
    assert len(outputs) >= 1
    assert len(outputs[0].items) == 2
    assert isinstance(outputs[0].items[0], Document)
    assert outputs[0].items[0].id == "https://github.com/test-org/test-repo/pull/3"
    assert isinstance(outputs[0].items[1], Document)
    assert outputs[0].items[1].id == "https://github.com/test-org/test-repo/pull/4"
    mock_source_operations.iter_pull_requests_by_cursor.assert_called_once_with(
        repo_full_name="test-org/test-repo",
        state="all",
        cursor_url=cursor_url,
        skip=0,
    )

    # The cursor run finished the stage, so the checkpoint is reset
    assert outputs[0].next_checkpoint.cursor_url is None
    assert outputs[0].next_checkpoint.num_retrieved == 0


def test_load_from_checkpoint_cursor_expiration(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test handling of cursor expiration during cursor-based pagination"""
    github_connector = build_github_connector()

    # Create a checkpoint with an expired cursor
    checkpoint = github_connector.build_dummy_checkpoint()
    checkpoint.cached_repo_ids = []
    checkpoint.cached_repo = _serialized(create_repo())
    checkpoint.cursor_url = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=expired"
    )
    checkpoint.num_retrieved = 3  # We've already retrieved 3 items

    def expired() -> Iterator[GitHubCursorItem[GitHubPullRequest]]:
        raise _api_error(422, "Cursor expired")
        yield  # A generator: the error comes on the first read.

    mock_source_operations.iter_pull_requests_by_cursor.side_effect = [
        expired(),
        _cursor_items((create_pr(number=4, title="PR 4"), None)),
    ]

    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        github_connector, 0, end_time, checkpoint
    )

    # Check that we got the remaining document after retrying from the beginning
    assert len(outputs) >= 1
    assert len(outputs[0].items) == 1
    assert isinstance(outputs[0].items[0], Document)
    assert outputs[0].items[0].id == "https://github.com/test-org/test-repo/pull/4"

    # Verify cursor URL was cleared in checkpoint
    assert outputs[0].next_checkpoint.cursor_url is None
    assert outputs[0].next_checkpoint.num_retrieved == 0

    # The retry restarted from the first page, skipping the 3 items read
    retry_call = mock_source_operations.iter_pull_requests_by_cursor.call_args_list[1]
    assert retry_call.kwargs["cursor_url"] is None
    assert retry_call.kwargs["skip"] == 3


def test_load_from_checkpoint_cursor_pagination_completion(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """Test behavior when cursor-based pagination completes and moves to next repository"""
    repo1 = create_repo(name="repo1", repo_id=1)
    repo2 = create_repo(name="repo2", repo_id=2)

    # Initialize connector with no specific repositories, so all repos are used
    github_connector = build_github_connector(repositories="")
    mock_source_operations.list_organization_repositories.return_value = [
        repo1,
        repo2,
    ]
    mock_source_operations.get_repository_by_id.side_effect = lambda *, repo_id: {
        1: repo1,
        2: repo2,
    }[repo_id]
    pr1 = create_pr(number=1, title="PR 1 Repo 1", repo_full_name="test-org/repo1")
    pr2 = create_pr(number=2, title="PR 2 Repo 1", repo_full_name="test-org/repo1")
    pr3 = create_pr(number=3, title="PR 3 Repo 2", repo_full_name="test-org/repo2")
    pr4 = create_pr(number=4, title="PR 4 Repo 2", repo_full_name="test-org/repo2")

    def list_pull_requests(
        *, repo_full_name: str, state: str, page: int
    ) -> list[GitHubPullRequest]:
        del state
        if repo_full_name == repo2.full_name:
            raise _api_error(422, "use cursor pagination")
        return [pr1, pr2] if page == 0 else []

    mock_source_operations.list_pull_requests.side_effect = list_pull_requests
    mock_source_operations.iter_pull_requests_by_cursor.side_effect = [
        _cursor_items((pr3, "cursor_step_2"), (pr4, None))
    ]

    checkpoint = github_connector.build_dummy_checkpoint()
    end_time = time.time()
    outputs = list(
        load_everything_from_checkpoint_connector_from_checkpoint(
            github_connector, 0, end_time, checkpoint
        )
    )

    # 1. Initial cp
    # 2. After repo2 PRs (cursor fallback) -> yields cp for repo2 issues
    # 3. After repo2 issues (empty) -> yields cp for repo1 PRs
    # 4. After repo1 PRs (page 0) -> yields cp for repo1 PRs page 1
    # 5. After repo1 PRs (page 1 empty) and repo1 issues (empty) -> final cp
    assert len(outputs) == 5

    # Output 0: Initial checkpoint, after listing the repos
    cp0 = outputs[0].next_checkpoint
    assert cp0.has_more
    assert cp0.cached_repo is not None
    assert cp0.cached_repo.id == repo2.id  # repo2 is popped first
    assert cp0.cached_repo_ids == [repo1.id]
    assert cp0.stage == GithubConnectorStage.PRS
    assert cp0.cursor_url is None

    # Output 1: After processing PRs for repo2 (via cursor fallback)
    assert len(outputs[1].items) == 2
    assert all(isinstance(item, Document) for item in outputs[1].items)
    assert {
        item.semantic_identifier for item in cast(list[Document], outputs[1].items)
    } == {"3: PR 3 Repo 2", "4: PR 4 Repo 2"}
    cp1 = outputs[1].next_checkpoint
    assert cp1.has_more
    assert cp1.cached_repo is not None
    assert cp1.cached_repo.id == repo2.id
    assert cp1.stage == GithubConnectorStage.ISSUES  # Moved to issues for repo2
    assert cp1.cursor_url is None  # Cursor completed and reset
    assert cp1.num_retrieved == 0  # Reset
    assert cp1.curr_page == 0  # Reset

    # Output 2: After processing Issues for repo2 (empty)
    assert len(outputs[2].items) == 0
    cp2 = outputs[2].next_checkpoint
    assert cp2.has_more
    assert cp2.cached_repo is not None
    assert cp2.cached_repo.id == repo1.id  # Moved to repo1
    assert cp2.cached_repo_ids == []  # Popped repo1 id
    assert cp2.stage == GithubConnectorStage.PRS  # For repo1
    assert cp2.cursor_url is None

    # Output 3: After processing PRs for repo1 (via offset, page 0)
    assert len(outputs[3].items) == 2
    assert all(isinstance(item, Document) for item in outputs[3].items)
    assert {
        item.semantic_identifier for item in cast(list[Document], outputs[3].items)
    } == {"1: PR 1 Repo 1", "2: PR 2 Repo 1"}
    cp3 = outputs[3].next_checkpoint
    assert cp3.has_more  # still need to do issues
    assert cp3.cached_repo is not None
    assert cp3.cached_repo.id == repo1.id
    assert cp3.stage == GithubConnectorStage.PRS  # Still PRS stage
    assert cp3.curr_page == 1  # Offset pagination incremented page for PRs
    assert cp3.cursor_url is None

    # Output 4: After processing PRs page 1 (empty) and Issues for repo1 (empty)
    assert len(outputs[4].items) == 0
    cp4 = outputs[4].next_checkpoint
    assert not cp4.has_more  # All done
    assert cp4.cached_repo is not None
    assert cp4.cached_repo.id == repo1.id  # Last processed repo
    assert cp4.stage == GithubConnectorStage.FILES  # FILES is the terminal stage
    assert cp4.curr_page == 0
    assert cp4.num_retrieved == 0
    assert cp4.cursor_url is None

    mock_source_operations.get_repository_by_id.assert_called_once_with(repo_id=1)
    assert [
        call.kwargs["repo_full_name"]
        for call in mock_source_operations.list_pull_requests.call_args_list
    ] == ["test-org/repo2", "test-org/repo1", "test-org/repo1"]


def test_a_rate_limited_repository_is_retried_not_skipped(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    """A rate limit while reading the configured repositories waits and
    retries; it does not drop the repository from the run."""
    github_connector = build_github_connector(repositories="a, b")
    repo_a = create_repo(name="a", repo_id=1)
    repo_b = create_repo(name="b", repo_id=2)
    mock_source_operations.get_repository.side_effect = [
        repo_a,
        GitHubRateLimitError("403 rate limited", status_code=403, secondary=True),
        repo_a,
        repo_b,
    ]

    with patch(
        "onyx.connectors.github.connector.sleep_after_rate_limit_exception"
    ) as mock_sleep:
        repos = github_connector.fetch_configured_repos()

    assert [repo.name for repo in repos] == ["a", "b"]
    assert mock_sleep.call_count == 1


def test_a_missing_repository_is_skipped(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> None:
    github_connector = build_github_connector(repositories="a, missing")
    mock_source_operations.get_repository.side_effect = [
        create_repo(name="a"),
        _api_error(404, "Not Found"),
    ]

    assert [repo.name for repo in github_connector.fetch_configured_repos()] == ["a"]


def test_the_profile_cache_starts_over_when_full(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
) -> None:
    github_connector = build_github_connector()

    with patch("onyx.connectors.github.connector._MAX_CACHED_USERS", 2):
        for login in ("a", "b", "c", "a"):
            github_connector._lookup_user(login)

    # "c" fills the cache past its size, so "a" is read again.
    assert mock_source_operations.get_user.call_count == 4
    assert len(github_connector._user_cache) == 2
