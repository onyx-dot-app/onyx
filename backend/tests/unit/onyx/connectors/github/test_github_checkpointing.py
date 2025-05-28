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
from github.PullRequest import PullRequest
from github.RateLimit import RateLimit
from github.Repository import Repository
from github.Requester import Requester

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import SerializedRepository
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
    # Add proper return typing for get_repo method
    mock.get_repo = MagicMock(return_value=MagicMock(spec=Repository))
    # Add proper return typing for get_organization method
    mock.get_organization = MagicMock()
    # Add proper return typing for get_user method
    mock.get_user = MagicMock()
    # Add proper return typing for get_rate_limit method
    mock.get_rate_limit = MagicMock(return_value=MagicMock(spec=RateLimit))
    # Add requester for repository deserialization
    mock.requester = MagicMock(spec=Requester)
    return mock


@pytest.fixture
def github_connector(
    repo_owner: str, repositories: str, mock_github_client: MagicMock
) -> Generator[GithubConnector, None, None]:
    connector = GithubConnector(
        repo_owner=repo_owner,
        repositories=repositories,
        include_prs=True,
        include_issues=True,
    )
    connector.github_client = mock_github_client
    yield connector


@pytest.fixture
def create_mock_pr() -> Callable[..., MagicMock]:
    def _create_mock_pr(
        number: int = 1,
        title: str = "Test PR",
        body: str = "Test Description",
        state: str = "open",
        merged: bool = False,
        updated_at: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
    ) -> MagicMock:
        """Helper to create a mock PullRequest object"""
        mock_pr = MagicMock(spec=PullRequest)
        mock_pr.number = number
        mock_pr.title = title
        mock_pr.body = body
        mock_pr.state = state
        mock_pr.merged = merged
        mock_pr.updated_at = updated_at
        mock_pr.html_url = f"https://github.com/test-org/test-repo/pull/{number}"
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
        return mock_issue

    return _create_mock_issue


@pytest.fixture
def create_mock_repo() -> Callable[..., MagicMock]:
    def _create_mock_repo(
        name: str = "test-repo",
        id: int = 1,
    ) -> MagicMock:
        """Helper to create a mock Repository object"""
        mock_repo = MagicMock(spec=Repository)
        mock_repo.name = name
        mock_repo.id = id
        mock_repo.raw_headers = {"status": "200 OK", "content-type": "application/json"}
        mock_repo.raw_data = {
            "id": str(id),
            "name": name,
            "full_name": f"test-org/{name}",
            "private": str(False),
            "description": "Test repository",
        }
        return mock_repo

    return _create_mock_repo


def test_load_from_checkpoint_happy_path(
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint - happy path"""
    # Set up mocked repo
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with rate limit handling"""
    # Set up mocked repo
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
            "onyx.connectors.github.connector._sleep_after_rate_limit_exception"
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with an empty repository"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with only PRs enabled"""
    # Configure connector to only include PRs
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with only issues enabled"""
    # Configure connector to only include issues
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
    github_connector: GithubConnector,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    error = GithubException(status=status_code, data={}, headers={})

    github_client = cast(Github, github_connector.github_client)
    get_repo_mock = cast(MagicMock, github_client.get_repo)
    get_repo_mock.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        github_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_success(
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Test successful validation"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    # Mock get_contents to simulate successful access
    mock_repo.get_contents.return_value = MagicMock()

    github_connector.validate_connector_settings()
    github_connector.github_client.get_repo.assert_called_once_with(
        f"{github_connector.repo_owner}/{github_connector.repositories}"
    )


def test_load_from_checkpoint_with_cursor_fallback(
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test loading from checkpoint with fallback to cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test resuming from a checkpoint that was using cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
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
    github_connector: GithubConnector,
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """Test handling of cursor expiration during cursor-based pagination"""
    # Set up mocked repo
    mock_repo = create_mock_repo()
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
