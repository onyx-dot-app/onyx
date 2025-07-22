import time
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from github import Github
from github import RateLimitExceededException
from github.GithubException import GithubException
from github.Issue import Issue
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.RateLimit import RateLimit
from github.Repository import Repository
from github.Requester import Requester

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import GithubConnectorStage
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)


@pytest.fixture
def repo_owner() -> str:
    return "test-org"


@pytest.fixture
def repositories() -> str:
    return "test-repo"


@pytest.fixture
def mock_github_client() -> MagicMock:
    """Create a mock GitHub client with proper typing"""
    mock = MagicMock(spec=Github)
    mock.get_repo = MagicMock()
    mock.get_organization = MagicMock()
    mock.get_user = MagicMock()
    mock.get_rate_limit = MagicMock(return_value=MagicMock(spec=RateLimit))
    mock._requester = MagicMock(spec=Requester)
    return mock


@pytest.fixture
def build_github_connector(
    repo_owner: str, repositories: str, mock_github_client: MagicMock
) -> Generator[Callable[..., GithubConnector], None, None]:
    def _github_connector(
        repo_owner: str = repo_owner, repositories: str = repositories
    ) -> GithubConnector:
        connector = GithubConnector(
            repo_owner=repo_owner,
            repositories=repositories,
            include_prs=True,
            include_issues=True,
        )
        connector.github_client = mock_github_client
        return connector

    yield _github_connector


@pytest.fixture
def create_mock_pr() -> Callable[..., MagicMock]:
    def _create_mock_pr(
        number: int = 1,
        title: str = "Test PR",
        body: str = "Test Description",
        state: str = "open",
        merged: bool = False,
        updated_at: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
        html_url: str | None = None,
    ) -> MagicMock:
        """Helper to create a mock PullRequest object"""
        mock_pr = MagicMock(spec=PullRequest)
        mock_pr.number = number
        mock_pr.title = title
        mock_pr.body = body
        mock_pr.state = state
        mock_pr.merged = merged
        mock_pr.updated_at = updated_at
        mock_pr.html_url = (
            html_url
            if html_url is not None
            else f"https://github.com/test-org/test-repo/pull/{number}"
        )
        mock_pr.raw_data = {}
        mock_pr.base = MagicMock()
        mock_pr.base.repo = MagicMock()
        mock_pr.base.repo.full_name = "test-org/test-repo"

        return mock_pr

    return _create_mock_pr


@pytest.fixture
def create_mock_issue() -> Callable[..., MagicMock]:
    def _create_mock_issue(
        number: int = 1,
        title: str = "Test Issue",
        body: str = "Test Description",
        state: str = "open",
        updated_at: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
    ) -> MagicMock:
        """Helper to create a mock Issue object"""
        mock_issue = MagicMock(spec=Issue)
        mock_issue.number = number
        mock_issue.title = title
        mock_issue.body = body
        mock_issue.state = state
        mock_issue.updated_at = updated_at
        mock_issue.html_url = f"https://github.com/test-org/test-repo/issues/{number}"
        mock_issue.pull_request = None  # Not a PR
        mock_issue.raw_data = {}

        # Mock the nested base.repo.full_name attribute
        mock_issue.repository = MagicMock()
        mock_issue.repository.full_name = "test-org/test-repo"

        return mock_issue

    return _create_mock_issue


@pytest.fixture
def create_mock_repo() -> Callable[..., MagicMock]:
    def _create_mock_repo(
        name: str = "test-repo",
        id: int = 1,
    ) -> MagicMock:
        mock_repo = MagicMock()
        mock_repo.name = name
        mock_repo.id = id

        headers_dict = {"status": "200 OK", "content-type": "application/json"}
        data_dict = {
            "id": id,
            "name": name,
            "full_name": f"test-org/{name}",
            "private": False,
            "description": "Test repository",
        }

        mock_repo.configure_mock(raw_headers=headers_dict, raw_data=data_dict)

        mock_repo.get_pulls = MagicMock()
        mock_repo.get_issues = MagicMock()
        mock_repo.get_contents = MagicMock()

        return mock_repo

    return _create_mock_repo


def test_load_from_checkpoint_happy_path(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint - happy path"""
    # Set up mocked repo
    github_connector = build_github_connector()
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PRs and issues
    mock_pr1 = create_mock_pr(number=1, title="PR 1")
    mock_pr2 = create_mock_pr(number=2, title="PR 2")
    mock_issue1 = create_mock_issue(number=1, title="Issue 1")
    mock_issue2 = create_mock_issue(number=2, title="Issue 2")

    # Mock get_pulls and get_issues methods
    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.side_effect = [
        [mock_pr1, mock_pr2],
        [],
    ]
    mock_repo.get_issues.return_value = MagicMock()
    mock_repo.get_issues.return_value.get_page.side_effect = [
        [mock_issue1, mock_issue2],
        [],
    ]

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

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
        assert (
            second_batch.items[0].id == "https://github.com/test-org/test-repo/issues/1"
        )
        assert isinstance(second_batch.items[1], Document)
        assert (
            second_batch.items[1].id == "https://github.com/test-org/test-repo/issues/2"
        )
        assert second_batch.next_checkpoint.has_more

        # Check third batch (finished checkpoint)
        third_batch = outputs[3]
        assert len(third_batch.items) == 0
        assert third_batch.next_checkpoint.has_more is False


def test_load_from_checkpoint_with_rate_limit(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with rate limit handling"""
    # Set up mocked repo
    github_connector = build_github_connector()
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PR
    mock_pr = create_mock_pr()

    # Mock get_pulls to raise RateLimitExceededException on first call
    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.side_effect = [
        RateLimitExceededException(403, {"message": "Rate limit exceeded"}, {}),
        [mock_pr],
        [],
    ]

    # Mock rate limit reset time
    mock_rate_limit = MagicMock(spec=RateLimit)
    mock_rate_limit.core.reset = datetime.now(timezone.utc)
    github_connector.github_client.get_rate_limit.return_value = mock_rate_limit

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
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
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with an empty repository"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector = build_github_connector()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Mock get_pulls and get_issues to return empty lists
    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.return_value = []
    mock_repo.get_issues.return_value = MagicMock()
    mock_repo.get_issues.return_value.get_page.return_value = []

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

        # Check that we got no documents
        assert len(outputs) == 2
        assert len(outputs[-1].items) == 0
        assert not outputs[-1].next_checkpoint.has_more


def test_load_from_checkpoint_with_prs_only(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with only PRs enabled"""
    # Configure connector to only include PRs
    github_connector = build_github_connector()
    github_connector.include_prs = True
    github_connector.include_issues = False

    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PRs
    mock_pr1 = create_mock_pr(number=1, title="PR 1")
    mock_pr2 = create_mock_pr(number=2, title="PR 2")

    # Mock get_pulls method
    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.side_effect = [
        [mock_pr1, mock_pr2],
        [],
    ]

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

        # Check that we only got PRs
        assert len(outputs) >= 2
        assert len(outputs[1].items) == 2
        assert all(
            isinstance(doc, Document) and "pull" in doc.id for doc in outputs[0].items
        )  # All documents should be PRs

        assert outputs[-1].next_checkpoint.has_more is False


def test_load_from_checkpoint_with_issues_only(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with only issues enabled"""
    # Configure connector to only include issues
    github_connector = build_github_connector()
    github_connector.include_prs = False
    github_connector.include_issues = True

    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked issues
    mock_issue1 = create_mock_issue(number=1, title="Issue 1")
    mock_issue2 = create_mock_issue(number=2, title="Issue 2")

    # Mock get_issues method
    mock_repo.get_issues.return_value = MagicMock()
    mock_repo.get_issues.return_value.get_page.side_effect = [
        [mock_issue1, mock_issue2],
        [],
    ]

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

        # Check that we only got issues
        assert len(outputs) >= 2
        assert len(outputs[1].items) == 2
        assert all(
            isinstance(doc, Document) and "issues" in doc.id for doc in outputs[0].items
        )  # All documents should be issues
        assert outputs[1].next_checkpoint.has_more

        assert outputs[-1].next_checkpoint.has_more is False


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
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    error = GithubException(status=status_code, data={}, headers={})

    github_connector = build_github_connector()
    github_client = cast(Github, github_connector.github_client)
    get_repo_mock = cast(MagicMock, github_client.get_repo)
    get_repo_mock.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        github_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_success(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Test successful validation"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector = build_github_connector()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Mock get_contents to simulate successful access
    mock_repo.get_contents.return_value = MagicMock()

    github_connector.validate_connector_settings()
    github_connector.github_client.get_repo.assert_called_once_with(
        f"{github_connector.repo_owner}/{github_connector.repositories}"
    )


def test_load_from_checkpoint_with_cursor_fallback(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with fallback to cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector = build_github_connector()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PRs
    mock_pr1 = create_mock_pr(number=1, title="PR 1")
    mock_pr2 = create_mock_pr(number=2, title="PR 2")

    # Create a mock paginated list that will raise the 422 error on get_page
    mock_paginated_list = MagicMock()
    mock_paginated_list.get_page.side_effect = [
        GithubException(
            422,
            {
                "message": "Pagination with the page parameter is not supported for large datasets. Use cursor"
            },
            {},
        ),
    ]

    # Create a new mock for cursor-based pagination
    mock_cursor_paginated_list = MagicMock()
    mock_cursor_paginated_list.__nextUrl = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=abc123"
    )
    mock_cursor_paginated_list.__iter__.return_value = iter([mock_pr1, mock_pr2])

    mock_repo.get_pulls.side_effect = [
        mock_paginated_list,
        mock_cursor_paginated_list,
    ]

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
        )

        # Check that we got the documents via cursor-based pagination
        assert len(outputs) >= 2
        assert len(outputs[1].items) == 2
        assert isinstance(outputs[1].items[0], Document)
        assert outputs[1].items[0].id == "https://github.com/test-org/test-repo/pull/1"
        assert isinstance(outputs[1].items[1], Document)
        assert outputs[1].items[1].id == "https://github.com/test-org/test-repo/pull/2"

        # Verify cursor URL is not set in checkpoint since pagination succeeded without failures
        assert outputs[1].next_checkpoint.cursor_url is None
        assert outputs[1].next_checkpoint.num_retrieved == 0


def test_load_from_checkpoint_resume_cursor_pagination(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test resuming from a checkpoint that was using cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector = build_github_connector()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PRs
    mock_pr3 = create_mock_pr(number=3, title="PR 3")
    mock_pr4 = create_mock_pr(number=4, title="PR 4")

    # Create a checkpoint that was using cursor-based pagination
    checkpoint = github_connector.build_dummy_checkpoint()
    checkpoint.cursor_url = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=abc123"
    )
    checkpoint.num_retrieved = 2

    # Mock get_pulls to use cursor-based pagination
    mock_paginated_list = MagicMock()
    mock_paginated_list.__nextUrl = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=def456"
    )
    mock_paginated_list.__iter__.return_value = iter([mock_pr3, mock_pr4])
    mock_repo.get_pulls.return_value = mock_paginated_list

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint with the checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            github_connector, 0, end_time, checkpoint
        )

        # Check that we got the documents via cursor-based pagination
        assert len(outputs) >= 2
        assert len(outputs[1].items) == 2
        assert isinstance(outputs[1].items[0], Document)
        assert outputs[1].items[0].id == "https://github.com/test-org/test-repo/pull/3"
        assert isinstance(outputs[1].items[1], Document)
        assert outputs[1].items[1].id == "https://github.com/test-org/test-repo/pull/4"

        # Verify cursor URL was stored in checkpoint
        assert outputs[1].next_checkpoint.cursor_url is None
        assert outputs[1].next_checkpoint.num_retrieved == 0


def test_load_from_checkpoint_cursor_expiration(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test handling of cursor expiration during cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector = build_github_connector()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Set up mocked PRs
    mock_pr4 = create_mock_pr(number=4, title="PR 4")

    # Create a checkpoint with an expired cursor
    checkpoint = github_connector.build_dummy_checkpoint()
    checkpoint.cursor_url = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=expired"
    )
    checkpoint.num_retrieved = 3  # We've already retrieved 3 items

    # Mock get_pulls to simulate cursor expiration by raising an error before any results
    mock_paginated_list = MagicMock()
    mock_paginated_list.__nextUrl = (
        "https://api.github.com/repos/test-org/test-repo/pulls?cursor=expired"
    )
    mock_paginated_list.__iter__.side_effect = GithubException(
        422, {"message": "Cursor expired"}, {}
    )

    # Create a new mock for successful retrieval after retry
    mock_retry_paginated_list = MagicMock()
    mock_retry_paginated_list.__nextUrl = None

    # Create an iterator that will yield the remaining PR
    def retry_iterator() -> Generator[PullRequest, None, None]:
        yield mock_pr4

    # Create a mock for the _Slice object that will be returned by pag_list[prev_num_objs:]
    mock_slice = MagicMock()
    mock_slice.__iter__.return_value = retry_iterator()

    # Set up the slice behavior for the retry paginated list
    mock_retry_paginated_list.__getitem__.return_value = mock_slice

    # Set up the side effect for get_pulls to return our mocks
    mock_repo.get_pulls.side_effect = [
        mock_paginated_list,
        mock_retry_paginated_list,
    ]

    # Mock SerializedRepository.to_Repository to return our mock repo
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        # Call load_from_checkpoint with the checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            github_connector, 0, end_time, checkpoint
        )

        # Check that we got the remaining document after retrying from the beginning
        assert len(outputs) >= 2
        assert len(outputs[1].items) == 1
        assert isinstance(outputs[1].items[0], Document)
        assert outputs[1].items[0].id == "https://github.com/test-org/test-repo/pull/4"

        # Verify cursor URL was cleared in checkpoint
        assert outputs[1].next_checkpoint.cursor_url is None
        assert outputs[1].next_checkpoint.num_retrieved == 0

        # Verify that the slice was called with the correct argument
        mock_retry_paginated_list.__getitem__.assert_called_once_with(slice(3, None))


def test_load_from_checkpoint_cursor_pagination_completion(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test behavior when cursor-based pagination completes and moves to next repository"""
    # Set up two repositories
    mock_repo1 = create_mock_repo(name="repo1", id=1)
    mock_repo2 = create_mock_repo(name="repo2", id=2)

    # Initialize connector with no specific repositories, so _get_all_repos is used
    github_connector = build_github_connector(repositories="")
    github_connector.github_client = mock_github_client
    mock_pr1 = create_mock_pr(
        number=1,
        title="PR 1 Repo 1",
        html_url="https://github.com/test-org/repo1/pull/1",
    )
    mock_pr2 = create_mock_pr(
        number=2,
        title="PR 2 Repo 1",
        html_url="https://github.com/test-org/repo1/pull/2",
    )
    mock_pr3 = create_mock_pr(
        number=3,
        title="PR 3 Repo 2",
        html_url="https://github.com/test-org/repo2/pull/3",
    )
    mock_pr4 = create_mock_pr(
        number=4,
        title="PR 4 Repo 2",
        html_url="https://github.com/test-org/repo2/pull/4",
    )
    checkpoint = github_connector.build_dummy_checkpoint()
    mock_paginated_list_repo1_prs = MagicMock(spec=PaginatedList)

    def get_page_repo1_side_effect(page_num: int) -> list[PullRequest]:
        if page_num == 0:
            return [mock_pr1, mock_pr2]
        else:
            return []

    mock_paginated_list_repo1_prs.get_page.side_effect = get_page_repo1_side_effect
    mock_repo2_cursor_paginator = MagicMock(spec=PaginatedList)

    def repo2_cursor_iterator() -> Generator[PullRequest, None, None]:
        print("setting next url to cursor_step_2")
        mock_repo2_cursor_paginator.__nextUrl = "cursor_step_2"
        yield mock_pr3
        print("setting next url to None")
        mock_repo2_cursor_paginator.__nextUrl = None
        yield mock_pr4

    mock_repo2_cursor_paginator.__iter__.return_value = repo2_cursor_iterator()
    mock_repo2_cursor_paginator.__nextUrl = None
    pull_requests_func_invocation_count = 0

    def replacement_pull_requests_func(
        repo: Repository,
    ) -> Callable[[], PaginatedList[PullRequest]]:
        nonlocal pull_requests_func_invocation_count
        pull_requests_func_invocation_count += 1
        current_repo_name = repo.name
        lambda_call_count_for_current_repo = 0

        def git_objs_lambda() -> PaginatedList[PullRequest]:
            nonlocal lambda_call_count_for_current_repo
            lambda_call_count_for_current_repo += 1
            if current_repo_name == mock_repo2.name:
                if lambda_call_count_for_current_repo == 1:
                    pl_for_offset_failure = MagicMock(spec=PaginatedList)

                    def get_page_raises_exception(page_num: int) -> list[PullRequest]:
                        raise GithubException(422, message="use cursor pagination")

                    pl_for_offset_failure.get_page.side_effect = (
                        get_page_raises_exception
                    )
                    return pl_for_offset_failure
                else:
                    return mock_repo2_cursor_paginator
            elif current_repo_name == mock_repo1.name:
                return mock_paginated_list_repo1_prs
            else:
                raise ValueError(f"Unexpected repo name: {current_repo_name}")

        return git_objs_lambda

    mock_requester = MagicMock(spec=Requester)
    github_connector.github_client._requester = mock_requester

    def get_repo_side_effect(repo_id: int) -> MagicMock:
        repo_to_return = None
        headers_dict = None
        data_dict = None
        if repo_id == 1:
            repo_to_return = mock_repo1
            headers_dict = {"status": "200 OK", "content-type": "application/json"}
            data_dict = {
                "id": 1,
                "name": "repo1",
                "full_name": "test-org/repo1",
                "private": False,
                "description": "Test repository",
            }
        elif repo_id == 2:
            repo_to_return = mock_repo2
            headers_dict = {"status": "200 OK", "content-type": "application/json"}
            data_dict = {
                "id": 2,
                "name": "repo2",
                "full_name": "test-org/repo2",
                "private": False,
                "description": "Test repository",
            }
        else:
            raise ValueError(f"Unexpected repo ID: {repo_id}")
        if repo_to_return and headers_dict and data_dict:
            repo_to_return.configure_mock(raw_headers=headers_dict, raw_data=data_dict)
        return repo_to_return

    mock_github_client.get_repo.side_effect = get_repo_side_effect

    def to_repository_side_effect(
        self_serialized_repo: SerializedRepository, requester_arg: Requester
    ) -> Repository:
        if self_serialized_repo.id == mock_repo1.id:
            return mock_repo1
        elif self_serialized_repo.id == mock_repo2.id:
            return mock_repo2
        raise ValueError(f"Unexpected repo ID: {self_serialized_repo.id}")

    mock_empty_issues_list = MagicMock(spec=PaginatedList)
    mock_empty_issues_list.get_page.return_value = []
    mock_empty_issues_list.__iter__.return_value = iter([])
    type(mock_empty_issues_list)._PaginatedList__nextUrl = None
    mock_repo1.get_issues.return_value = mock_empty_issues_list
    mock_repo2.get_issues.return_value = mock_empty_issues_list
    with patch.object(
        github_connector, "get_all_repos", return_value=[mock_repo1, mock_repo2]
    ), patch.object(
        github_connector,
        "_pull_requests_func",
        side_effect=replacement_pull_requests_func,
    ), patch.object(
        SerializedRepository,
        "to_Repository",
        side_effect=to_repository_side_effect,
        autospec=True,
    ) as mock_to_repository:
        end_time = time.time()
        outputs = list(
            load_everything_from_checkpoint_connector_from_checkpoint(
                github_connector, 0, end_time, checkpoint
            )
        )

    # --- Assertions ---
    # Expected outputs: 5 based on the latest logic refinement
    # 1. Initial cp
    # 2. After repo2 PRs (cursor fallback) -> yields cp for repo2 issues
    # 3. After repo2 issues (empty) -> yields cp for repo1 PRs
    # 4. After repo1 PRs (page 0) -> yields cp for repo1 PRs page 1
    # 5. After repo1 PRs (page 1 empty) and repo1 issues (empty) -> yields final cp

    assert (
        len(outputs) == 5
    )  # Initial, Repo2-PRs, Repo2-Issues, Repo1-PRs-P0, Repo1-Issues(final)

    # Output 0: Initial checkpoint, after _get_all_repos
    cp0 = outputs[0].next_checkpoint
    assert cp0.has_more
    assert cp0.cached_repo is not None
    assert cp0.cached_repo.id == mock_repo2.id  # mock_repo2 is popped first
    assert cp0.cached_repo_ids == [mock_repo1.id]
    assert cp0.stage == GithubConnectorStage.PRS
    assert cp0.cursor_url is None

    # Output 1: After processing PRs for mock_repo2 (via cursor fallback)
    # Items should be pr3, pr4
    assert len(outputs[1].items) == 2
    assert all(isinstance(item, Document) for item in outputs[1].items)
    assert {
        item.semantic_identifier for item in cast(list[Document], outputs[1].items)
    } == {"3: PR 3 Repo 2", "4: PR 4 Repo 2"}
    cp1 = outputs[1].next_checkpoint
    assert (
        cp1.has_more
    )  # Still have repo1 in cached_repo_ids at the time checkpoint is yielded
    assert cp1.cached_repo is not None
    assert cp1.cached_repo.id == mock_repo2.id
    assert cp1.stage == GithubConnectorStage.ISSUES  # Moved to issues for repo2
    assert cp1.cursor_url is None  # Cursor completed and reset
    assert cp1.num_retrieved == 0  # Reset
    assert cp1.curr_page == 0  # Reset

    # Output 2: After processing Issues for mock_repo2 (empty)
    assert len(outputs[2].items) == 0
    cp2 = outputs[2].next_checkpoint
    assert cp2.has_more  # Checkpoint yielded BEFORE final has_more check
    assert cp2.cached_repo is not None
    assert cp2.cached_repo.id == mock_repo1.id  # Moved to repo1
    assert cp2.cached_repo_ids == []  # Popped repo1 id
    assert cp2.stage == GithubConnectorStage.PRS  # For repo1
    assert cp2.cursor_url is None

    # Output 3: After processing PRs for mock_repo1 (via offset, page 0)
    assert len(outputs[3].items) == 2
    assert all(isinstance(item, Document) for item in outputs[3].items)
    assert {
        item.semantic_identifier for item in cast(list[Document], outputs[3].items)
    } == {"1: PR 1 Repo 1", "2: PR 2 Repo 1"}
    cp3 = outputs[3].next_checkpoint
    # This checkpoint is returned early because offset had items. has_more reflects state then.
    assert cp3.has_more  # still need to do issues
    assert cp3.cached_repo is not None
    assert cp3.cached_repo.id == mock_repo1.id
    assert cp3.stage == GithubConnectorStage.PRS  # Still PRS stage
    assert cp3.curr_page == 1  # Offset pagination incremented page for PRs
    assert cp3.cursor_url is None

    # Output 4: After processing PRs page 1 (empty) and Issues for mock_repo1 (empty) - Final checkpoint
    assert len(outputs[4].items) == 0
    cp4 = outputs[4].next_checkpoint
    assert not cp4.has_more  # All done
    assert cp4.cached_repo is not None
    assert cp4.cached_repo.id == mock_repo1.id  # Last processed repo
    assert (
        cp4.stage == GithubConnectorStage.PRS
    )  # Reset for a hypothetical next run/repo
    assert cp4.curr_page == 0
    assert cp4.num_retrieved == 0
    assert cp4.cursor_url is None

    # Verify to_Repository calls
    print(mock_to_repository.call_args_list)
    assert (
        mock_to_repository.call_count == 4
    )  # Twice for repo2, twice for repo1 (issues don't need it)
    assert (
        mock_to_repository.call_args_list[0][0][0].id == mock_repo2.id
    )  # First call was for repo2
    assert (
        mock_to_repository.call_args_list[1][0][0].id == mock_repo2.id
    )  # Second call was for repo2
    assert (
        mock_to_repository.call_args_list[2][0][0].id == mock_repo1.id
    )  # Third call was for repo1
    assert (
        mock_to_repository.call_args_list[3][0][0].id == mock_repo1.id
    )  # Fourth call was for repo1

    # Verify _pull_requests_func was invoked for both repos' PR stages
    assert (
        pull_requests_func_invocation_count == 3
    )  # twice for repo2 PRs, once for repo1 PRs
