from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira.resources import Issue
from pytest_mock import MockFixture

from onyx.connectors.jira.connector import _perform_jql_search
from onyx.connectors.jira.connector import process_jira_issue


@pytest.fixture
def mock_jira_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_issue_small() -> MagicMock:
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "Small description"
    fields.comment = MagicMock()
    fields.comment.comments = [
        MagicMock(body="Small comment 1"),
        MagicMock(body="Small comment 2"),
    ]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "John Doe"
    fields.reporter.emailAddress = "john@example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "John Doe"
    fields.assignee.emailAddress = "john@example.com"
    fields.summary = "Small Issue"
    fields.updated = "2023-01-01T00:00:00+0000"
    fields.labels = []

    issue.fields = fields
    issue.key = "SMALL-1"
    return issue


@pytest.fixture
def mock_issue_large() -> MagicMock:
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "a" * 99_000
    fields.comment = MagicMock()
    fields.comment.comments = [
        MagicMock(body="Large comment " * 1000),
        MagicMock(body="Another large comment " * 1000),
    ]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "Jane Doe"
    fields.reporter.emailAddress = "jane@example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "Jane Doe"
    fields.assignee.emailAddress = "jane@example.com"
    fields.summary = "Large Issue"
    fields.updated = "2023-01-02T00:00:00+0000"
    fields.labels = []

    issue.fields = fields
    issue.key = "LARGE-1"
    return issue


@pytest.fixture
def mock_jira_api_version() -> Generator[Any, Any, Any]:
    with patch("onyx.connectors.jira.utils.JIRA_CLOUD_API_VERSION", "3"):
        with patch("onyx.connectors.jira.utils.JIRA_SERVER_API_VERSION", "2"):
            yield


@pytest.fixture
def patched_environment(
    mock_jira_api_version: MockFixture,
) -> Generator[Any, Any, Any]:
    yield


def test_fetch_jira_issues_batch_small_ticket(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_jira_client, "project = TEST", 0, 50))
    assert len(issues) == 1

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 1
    doc = docs[0]
    assert doc is not None  # Type assertion for mypy
    assert doc.id.endswith("/SMALL-1")
    assert doc.sections[0].text is not None
    assert "Small description" in doc.sections[0].text
    assert "Small comment 1" in doc.sections[0].text
    assert "Small comment 2" in doc.sections[0].text


def test_fetch_jira_issues_batch_large_ticket(
    mock_jira_client: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_large]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_jira_client, "project = TEST", 0, 50))
    assert len(issues) == 1

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 0  # The large ticket should be skipped


def test_fetch_jira_issues_batch_mixed_tickets(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small, mock_issue_large]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_jira_client, "project = TEST", 0, 50))
    assert len(issues) == 2

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 1  # Only the small ticket should be included
    doc = docs[0]
    assert doc is not None  # Type assertion for mypy
    assert doc.id.endswith("/SMALL-1")


@patch("onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 50)
def test_fetch_jira_issues_batch_custom_size_limit(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small, mock_issue_large]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_jira_client, "project = TEST", 0, 50))
    assert len(issues) == 2

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 0  # Both tickets should be skipped due to the low size limit
