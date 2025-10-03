import time
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from jira import JIRAError
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.utils.logger import setup_logger
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

logger = setup_logger()
PAGE_SIZE = 2


@pytest.fixture
def jira_connector(
    jira_base_url: str, project_key: str, mock_jira_client: MagicMock
) -> Generator[JiraConnector, None, None]:
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        comment_email_blacklist=["blacklist@example.com"],
        labels_to_skip=["secret", "sensitive"],
    )
    connector._jira_client = mock_jira_client
    connector._jira_client.client_info.return_value = jira_base_url
    connector._jira_client._options = MagicMock()
    connector._jira_client._options.return_value = {
        "rest_api_version": JIRA_SERVER_API_VERSION
    }
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_issue() -> Callable[..., MagicMock]:
    def _create_mock_issue(
        key: str = "TEST-123",
        summary: str = "Test Issue",
        updated: str = "2023-01-01T12:00:00.000+0000",
        description: str = "Test Description",
        labels: list[str] | None = None,
    ) -> MagicMock:
        """Helper to create a mock Issue object"""
        mock_issue = MagicMock(spec=Issue)
        # Create fields attribute first
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = summary
        mock_issue.fields.updated = updated
        mock_issue.fields.description = description
        mock_issue.fields.labels = labels or []

        # Set up creator and assignee for testing owner extraction
        mock_issue.fields.reporter = MagicMock()
        mock_issue.fields.reporter.displayName = "Test Creator"
        mock_issue.fields.reporter.emailAddress = "creator@example.com"

        mock_issue.fields.assignee = MagicMock()
        mock_issue.fields.assignee.displayName = "Test Assignee"
        mock_issue.fields.assignee.emailAddress = "assignee@example.com"

        # Set up priority, status, and resolution
        mock_issue.fields.priority = MagicMock()
        mock_issue.fields.priority.name = "High"

        mock_issue.fields.status = MagicMock()
        mock_issue.fields.status.name = "In Progress"

        mock_issue.fields.resolution = MagicMock()
        mock_issue.fields.resolution.name = "Fixed"

        # Add raw field for accessing through API version check
        mock_issue.raw = {"fields": {"description": description}}

        return mock_issue

    return _create_mock_issue


def test_load_credentials(jira_connector: JiraConnector) -> None:
    """Test loading credentials"""
    with patch("onyx.connectors.jira.connector.build_jira_client") as mock_build_client:
        mock_build_client.return_value = jira_connector._jira_client
        credentials = {
            "jira_user_email": "user@example.com",
            "jira_api_token": "token123",
        }

        result = jira_connector.load_credentials(credentials)

        mock_build_client.assert_called_once_with(
            credentials=credentials,
            jira_base=jira_connector.jira_base,
            scoped_token=False,
        )
        assert result is None
        assert jira_connector._jira_client == mock_build_client.return_value


def test_get_jql_query_with_project(jira_connector: JiraConnector) -> None:
    """Test JQL query generation with project specified"""
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    query = jira_connector._get_jql_query(start, end)

    # Check that the project part and time part are both in the query
    assert f'project = "{jira_connector.jira_project}"' in query
    assert "updated >= '2023-01-01 00:00'" in query
    assert "updated <= '2023-01-02 00:00'" in query
    assert " AND " in query


def test_get_jql_query_without_project(jira_base_url: str) -> None:
    """Test JQL query generation without project specified"""
    # Create connector without project key
    connector = JiraConnector(jira_base_url=jira_base_url)

    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    query = connector._get_jql_query(start, end)

    # Check that only time part is in the query
    assert "project =" not in query
    assert "updated >= '2023-01-01 00:00'" in query
    assert "updated <= '2023-01-02 00:00'" in query


def test_load_from_checkpoint_happy_path(
    jira_connector: JiraConnector, create_mock_issue: Callable[..., MagicMock]
) -> None:
    """Test loading from checkpoint - happy path"""
    # Set up mocked issues
    mock_issue1 = create_mock_issue(key="TEST-1", summary="Issue 1")
    mock_issue2 = create_mock_issue(key="TEST-2", summary="Issue 2")
    mock_issue3 = create_mock_issue(key="TEST-3", summary="Issue 3")

    # Only mock the search_issues method
    jira_client = cast(JIRA, jira_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.side_effect = [
        [mock_issue1, mock_issue2],
        [mock_issue3],
        [],
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(jira_connector, 0, end_time)

    # Check that the documents were returned
    assert len(outputs) == 2

    checkpoint_output1 = outputs[0]
    assert len(checkpoint_output1.items) == 2
    document1 = checkpoint_output1.items[0]
    assert isinstance(document1, Document)
    assert document1.id == "https://jira.example.com/browse/TEST-1"
    document2 = checkpoint_output1.items[1]
    assert isinstance(document2, Document)
    assert document2.id == "https://jira.example.com/browse/TEST-2"
    assert checkpoint_output1.next_checkpoint == JiraConnectorCheckpoint(
        offset=2,
        has_more=True,
    )

    checkpoint_output2 = outputs[1]
    assert len(checkpoint_output2.items) == 1
    document3 = checkpoint_output2.items[0]
    assert isinstance(document3, Document)
    assert document3.id == "https://jira.example.com/browse/TEST-3"
    assert checkpoint_output2.next_checkpoint == JiraConnectorCheckpoint(
        offset=3,
        has_more=False,
    )

    # Check that search_issues was called with the right parameters
    assert search_issues_mock.call_count == 2
    args, kwargs = search_issues_mock.call_args_list[0]
    assert kwargs["startAt"] == 0
    assert kwargs["maxResults"] == PAGE_SIZE

    args, kwargs = search_issues_mock.call_args_list[1]
    assert kwargs["startAt"] == 2
    assert kwargs["maxResults"] == PAGE_SIZE


def test_load_from_checkpoint_with_issue_processing_error(
    jira_connector: JiraConnector, create_mock_issue: Callable[..., MagicMock]
) -> None:
    """Test loading from checkpoint with a mix of successful and failed issue processing across multiple batches"""
    # Set up mocked issues for first batch
    mock_issue1 = create_mock_issue(key="TEST-1", summary="Issue 1")
    mock_issue2 = create_mock_issue(key="TEST-2", summary="Issue 2")
    # Set up mocked issues for second batch
    mock_issue3 = create_mock_issue(key="TEST-3", summary="Issue 3")
    mock_issue4 = create_mock_issue(key="TEST-4", summary="Issue 4")

    # Mock search_issues to return our mock issues in batches
    jira_client = cast(JIRA, jira_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.side_effect = [
        [mock_issue1, mock_issue2],  # First batch
        [mock_issue3, mock_issue4],  # Second batch
        [],  # Empty batch to indicate end
    ]

    # Mock process_jira_issue to succeed for some issues and fail for others
    def mock_process_side_effect(
        jira_base_url: str, issue: Issue, *args: Any, **kwargs: Any
    ) -> Document | None:
        if issue.key in ["TEST-1", "TEST-3"]:
            return Document(
                id=f"https://jira.example.com/browse/{issue.key}",
                sections=[],
                source=DocumentSource.JIRA,
                semantic_identifier=f"{issue.key}: {issue.fields.summary}",
                title=f"{issue.key} {issue.fields.summary}",
                metadata={},
            )
        else:
            raise Exception(f"Processing error for {issue.key}")

    with patch("onyx.connectors.jira.connector.process_jira_issue") as mock_process:
        mock_process.side_effect = mock_process_side_effect

        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(jira_connector, 0, end_time)

        assert len(outputs) == 3

        # Check first batch
        first_batch = outputs[0]
        assert len(first_batch.items) == 2
        # First item should be successful
        assert isinstance(first_batch.items[0], Document)
        assert first_batch.items[0].id == "https://jira.example.com/browse/TEST-1"
        # Second item should be a failure
        assert isinstance(first_batch.items[1], ConnectorFailure)
        assert first_batch.items[1].failed_document is not None
        assert first_batch.items[1].failed_document.document_id == "TEST-2"
        assert "Failed to process Jira issue" in first_batch.items[1].failure_message
        # Check checkpoint indicates more items (full batch)
        assert first_batch.next_checkpoint.has_more is True
        assert first_batch.next_checkpoint.offset == 2

        # Check second batch
        second_batch = outputs[1]
        assert len(second_batch.items) == 2
        # First item should be successful
        assert isinstance(second_batch.items[0], Document)
        assert second_batch.items[0].id == "https://jira.example.com/browse/TEST-3"
        # Second item should be a failure
        assert isinstance(second_batch.items[1], ConnectorFailure)
        assert second_batch.items[1].failed_document is not None
        assert second_batch.items[1].failed_document.document_id == "TEST-4"
        assert "Failed to process Jira issue" in second_batch.items[1].failure_message
        # Check checkpoint indicates more items
        assert second_batch.next_checkpoint.has_more is True
        assert second_batch.next_checkpoint.offset == 4

        # Check third, empty batch
        third_batch = outputs[2]
        assert len(third_batch.items) == 0
        assert third_batch.next_checkpoint.has_more is False
        assert third_batch.next_checkpoint.offset == 4


def test_load_from_checkpoint_with_skipped_issue(
    jira_connector: JiraConnector, create_mock_issue: Callable[..., MagicMock]
) -> None:
    """Test loading from checkpoint with an issue that should be skipped due to labels"""
    LABEL_TO_SKIP = "secret"
    jira_connector.labels_to_skip = {LABEL_TO_SKIP}

    # Set up mocked issue with a label to skip
    mock_issue = create_mock_issue(
        key="TEST-1", summary="Issue 1", labels=[LABEL_TO_SKIP]
    )

    # Mock search_issues to return our mock issue
    jira_client = cast(JIRA, jira_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.return_value = [mock_issue]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(jira_connector, 0, end_time)

    assert len(outputs) == 1
    checkpoint_output = outputs[0]
    # Check that no documents were returned
    assert len(checkpoint_output.items) == 0


def test_retrieve_all_slim_docs_perm_sync(
    jira_connector: JiraConnector, create_mock_issue: Any
) -> None:
    """Test retrieving all slim documents"""
    # Set up mocked issues
    mock_issue1 = create_mock_issue(key="TEST-1")
    mock_issue2 = create_mock_issue(key="TEST-2")

    # Mock search_issues to return our mock issues
    jira_client = cast(JIRA, jira_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.return_value = [mock_issue1, mock_issue2]

    # Mock best_effort_get_field_from_issue to return the keys
    with patch(
        "onyx.connectors.jira.connector.best_effort_get_field_from_issue"
    ) as mock_field:
        mock_field.side_effect = ["TEST-1", "TEST-2"]

        # Mock build_jira_url to return URLs
        with patch("onyx.connectors.jira.connector.build_jira_url") as mock_url:
            mock_url.side_effect = [
                "https://jira.example.com/browse/TEST-1",
                "https://jira.example.com/browse/TEST-2",
            ]

            # Call retrieve_all_slim_docs_perm_sync
            batches = list(jira_connector.retrieve_all_slim_docs_perm_sync(0, 100))

            # Check that a batch with 2 documents was returned
            assert len(batches) == 1
            assert len(batches[0]) == 2
            assert isinstance(batches[0][0], SlimDocument)
            assert batches[0][0].id == "https://jira.example.com/browse/TEST-1"
            assert batches[0][1].id == "https://jira.example.com/browse/TEST-2"

            # Check that search_issues was called with the right parameters
            search_issues_mock.assert_called_once()
            args, kwargs = search_issues_mock.call_args


@pytest.mark.parametrize(
    "status_code,expected_exception,expected_message",
    [
        (
            401,
            CredentialExpiredError,
            "Jira credential appears to be expired or invalid",
        ),
        (
            403,
            InsufficientPermissionsError,
            "Your Jira token does not have sufficient permissions",
        ),
        (
            # This test used to check for 404 project not found, but the jira validation logic for 404
            # now returns an UnexpectedValidationError when no error text is provided.
            # There's no point in passing the expected message and asserting it exists in the raised error
            # If tested in the UI, wrong project key will still produce the expected error.
            404,
            UnexpectedValidationError,
            "Unexpected Jira error during validation",
        ),
        (
            429,
            ConnectorValidationError,
            "Validation failed due to Jira rate-limits being exceeded",
        ),
    ],
)
def test_validate_connector_settings_errors(
    jira_connector: JiraConnector,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    error = JIRAError(status_code=status_code)

    jira_client = cast(JIRA, jira_connector._jira_client)
    project_mock = cast(MagicMock, jira_client.project)
    project_mock.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        jira_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_with_project_success(
    jira_connector: JiraConnector,
) -> None:
    """Test successful validation with project specified"""
    jira_client = cast(JIRA, jira_connector._jira_client)
    project_mock = cast(MagicMock, jira_client.project)
    project_mock.return_value = MagicMock()
    jira_connector.validate_connector_settings()
    project_mock.assert_called_once_with(jira_connector.jira_project)


def test_validate_connector_settings_without_project_success(
    jira_base_url: str,
) -> None:
    """Test successful validation without project specified"""
    connector = JiraConnector(jira_base_url=jira_base_url)
    connector._jira_client = MagicMock()
    connector._jira_client.projects.return_value = [MagicMock()]

    connector.validate_connector_settings()
    connector._jira_client.projects.assert_called_once()
