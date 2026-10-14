import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.models import ConnectorFailure, Document, SlimDocument
from onyx.utils.logger import setup_logger
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

logger = setup_logger()
PAGE_SIZE = 2

RawIssueFactory = Callable[..., dict[str, Any]]


def test_load_credentials(jira_connector: JiraConnector) -> None:
    """Loading credentials builds a gateway bound to the connector's site."""
    credentials = {
        "jira_user_email": "user@example.com",
        "jira_api_token": "token123",
    }

    result = jira_connector.load_credentials(credentials)

    assert result is None
    gateway = jira_connector.source_operations
    assert isinstance(gateway, JiraSourceOperations)
    assert gateway.connector_specific_config == {
        "jira_base_url": jira_connector.jira_base,
        "scoped_token": False,
    }
    assert gateway.credentials_provider.get_credentials() == credentials


def test_get_jql_query_with_project(jira_connector: JiraConnector) -> None:
    """Poll windows are unquoted epoch-ms, not naive datetimes."""
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    query = jira_connector._get_jql_query(start, end)

    assert f'project = "{jira_connector.jira_project}"' in query
    assert f"updated >= {int(start * 1000)}" in query
    assert f"updated <= {int(end * 1000)}" in query
    assert "2023-01-01 00:00" not in query
    assert " AND " in query


@pytest.mark.parametrize(
    "project_key,jql_query,expected_scope",
    [
        ("   ", None, None),
        (" AS ", None, 'project = "AS"'),
        ("AS", "  ", 'project = "AS"'),
        (None, " project = X ", "(project = X)"),
    ],
    ids=["blank-key", "padded-key", "blank-jql", "padded-jql"],
)
def test_blank_scope_fields_are_not_set(
    jira_base_url: str,
    project_key: str | None,
    jql_query: str | None,
    expected_scope: str | None,
) -> None:
    """The create form sends blank fields; the connector strips them."""
    connector = JiraConnector(
        jira_base_url=jira_base_url, project_key=project_key, jql_query=jql_query
    )

    query: str = connector._get_jql_query(0, 1)

    if expected_scope is None:
        assert query.startswith("updated >=")
    else:
        assert query.startswith(f"{expected_scope} AND updated >=")


def test_get_jql_query_without_project(jira_base_url: str) -> None:
    """Poll windows stay epoch-ms when no project key is set."""
    connector = JiraConnector(jira_base_url=jira_base_url)

    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    query = connector._get_jql_query(start, end)

    assert "project =" not in query
    assert f"updated >= {int(start * 1000)}" in query
    assert f"updated <= {int(end * 1000)}" in query
    assert "2023-01-01 00:00" not in query


def test_load_from_checkpoint_happy_path(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Test loading from checkpoint - happy path"""
    # Set up mocked issues
    mock_issue1 = create_mock_issue(key="TEST-1", summary="Issue 1")
    mock_issue2 = create_mock_issue(key="TEST-2", summary="Issue 2")
    mock_issue3 = create_mock_issue(key="TEST-3", summary="Issue 3")

    # Only mock the search_issues method
    search_issues_mock = mock_source_operations.search_issues
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
        seen_hierarchy_node_ids=["TEST"],
    )

    checkpoint_output2 = outputs[1]
    assert len(checkpoint_output2.items) == 1
    document3 = checkpoint_output2.items[0]
    assert isinstance(document3, Document)
    assert document3.id == "https://jira.example.com/browse/TEST-3"
    assert checkpoint_output2.next_checkpoint == JiraConnectorCheckpoint(
        offset=3,
        has_more=False,
        seen_hierarchy_node_ids=["TEST"],
    )

    # Check that search_issues was called with the right parameters
    assert search_issues_mock.call_count == 2
    args, kwargs = search_issues_mock.call_args_list[0]
    assert kwargs["start_at"] == 0
    assert kwargs["max_results"] == PAGE_SIZE

    args, kwargs = search_issues_mock.call_args_list[1]
    assert kwargs["start_at"] == 2
    assert kwargs["max_results"] == PAGE_SIZE


def test_load_from_checkpoint_with_issue_processing_error(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Test loading from checkpoint with a mix of successful and failed issue processing across multiple batches"""
    # Set up mocked issues for first batch
    mock_issue1 = create_mock_issue(key="TEST-1", summary="Issue 1")
    mock_issue2 = create_mock_issue(key="TEST-2", summary="Issue 2")
    # Set up mocked issues for second batch
    mock_issue3 = create_mock_issue(key="TEST-3", summary="Issue 3")
    mock_issue4 = create_mock_issue(key="TEST-4", summary="Issue 4")

    # Mock search_issues to return our mock issues in batches
    search_issues_mock = mock_source_operations.search_issues
    search_issues_mock.side_effect = [
        [mock_issue1, mock_issue2],  # First batch
        [mock_issue3, mock_issue4],  # Second batch
        [],  # Empty batch to indicate end
    ]

    # Mock process_jira_issue to succeed for some issues and fail for others
    def mock_process_side_effect(
        jira_base_url: str,  # noqa: ARG001
        issue: dict[str, Any],
        *args: Any,  # noqa: ARG001
        **kwargs: Any,  # noqa: ARG001
    ) -> Document | None:
        key = issue["key"]
        if key in ["TEST-1", "TEST-3"]:
            return Document(
                id=f"https://jira.example.com/browse/{key}",
                sections=[],
                source=DocumentSource.JIRA,
                semantic_identifier=f"{key}: {issue['fields']['summary']}",
                title=f"{key} {issue['fields']['summary']}",
                metadata={},
            )
        else:
            raise Exception(f"Processing error for {key}")

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
        # Must match the Document.id shape the success path emits above, since
        # consumers correlate failures to documents by this value.
        assert (
            first_batch.items[1].failed_document.document_id
            == "https://jira.example.com/browse/TEST-2"
        )
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
        assert (
            second_batch.items[1].failed_document.document_id
            == "https://jira.example.com/browse/TEST-4"
        )
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
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Test loading from checkpoint with an issue that should be skipped due to labels"""
    LABEL_TO_SKIP = "secret"
    jira_connector.labels_to_skip = {LABEL_TO_SKIP}

    # Set up mocked issue with a label to skip
    mock_issue = create_mock_issue(
        key="TEST-1", summary="Issue 1", labels=[LABEL_TO_SKIP]
    )

    # Mock search_issues to return our mock issue
    search_issues_mock = mock_source_operations.search_issues
    search_issues_mock.return_value = [mock_issue]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(jira_connector, 0, end_time)

    assert len(outputs) == 1
    checkpoint_output = outputs[0]
    # Check that no documents were returned
    assert len(checkpoint_output.items) == 0


def test_retrieve_all_slim_docs_perm_sync(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Test retrieving all slim documents"""
    # Set up mocked issues with proper project fields
    mock_issue1 = create_mock_issue(key="TEST-1", project_key="TEST")
    mock_issue2 = create_mock_issue(key="TEST-2", project_key="TEST")

    # Mock search_issues to return our mock issues
    search_issues_mock = mock_source_operations.search_issues
    search_issues_mock.return_value = [mock_issue1, mock_issue2]

    # Call retrieve_all_slim_docs_perm_sync
    batches = list(jira_connector.retrieve_all_slim_docs_perm_sync(0, 100))

    # Check that a batch was returned (may include hierarchy nodes + slim docs)
    assert len(batches) == 1
    # Filter to just slim documents for checking
    slim_docs = [item for item in batches[0] if isinstance(item, SlimDocument)]
    assert len(slim_docs) == 2
    assert slim_docs[0].id == "https://jira.example.com/browse/TEST-1"
    assert slim_docs[1].id == "https://jira.example.com/browse/TEST-2"

    # Check that search_issues was called
    search_issues_mock.assert_called_once()


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
    mock_source_operations: MagicMock,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    error = JiraApiError("error", status_code=status_code, text=None)

    mock_source_operations.get_project.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        jira_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_with_project_success(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test successful validation with project specified"""
    mock_source_operations.get_project.return_value = {"key": "TEST"}
    jira_connector.validate_connector_settings()
    mock_source_operations.get_project.assert_called_once_with(
        project_key=jira_connector.jira_project
    )


def test_validate_connector_settings_without_project_success(
    jira_base_url: str,
    mock_source_operations: MagicMock,
) -> None:
    """Test successful validation without project specified"""
    connector = JiraConnector(jira_base_url=jira_base_url)
    connector._source_operations = mock_source_operations
    mock_source_operations.list_projects.return_value = [{"key": "TEST"}]

    connector.validate_connector_settings()
    mock_source_operations.list_projects.assert_called_once()
