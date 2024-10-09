from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira.resources import Issue
from pytest_mock import MockFixture

from danswer.connectors.danswer_jira.connector import fetch_jira_issues_batch


@pytest.fixture
def mock_jira_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_issue_small() -> MagicMock:
    issue = MagicMock()
    issue.key = "SMALL-1"
    issue.fields.description = "Small description"
    issue.fields.comment.comments = [
        MagicMock(body="Small comment 1"),
        MagicMock(body="Small comment 2"),
    ]
    issue.fields.creator.displayName = "John Doe"
    issue.fields.creator.emailAddress = "john@example.com"
    issue.fields.summary = "Small Issue"
    issue.fields.updated = "2023-01-01T00:00:00+0000"
    issue.fields.labels = []
    return issue


@pytest.fixture
def mock_issue_large() -> MagicMock:
    # This will be larger than 100KB
    issue = MagicMock()
    issue.key = "LARGE-1"
    issue.fields.description = "a" * 99_000
    issue.fields.comment.comments = [
        MagicMock(body="Large comment " * 1000),
        MagicMock(body="Another large comment " * 1000),
    ]
    issue.fields.creator.displayName = "Jane Doe"
    issue.fields.creator.emailAddress = "jane@example.com"
    issue.fields.summary = "Large Issue"
    issue.fields.updated = "2023-01-02T00:00:00+0000"
    issue.fields.labels = []
    return issue


@pytest.fixture
def patched_type() -> Callable[[Any], type]:
    def _patched_type(obj: Any) -> type:
        if isinstance(obj, MagicMock):
            return Issue
        return type(obj)

    return _patched_type


@pytest.fixture
def mock_jira_api_version() -> Generator[Any, Any, Any]:
    with patch("danswer.connectors.danswer_jira.connector.JIRA_API_VERSION", "2"):
        yield


@pytest.fixture
def patched_environment(
    patched_type: type,
    mock_jira_api_version: MockFixture,
) -> Generator[Any, Any, Any]:
    with patch("danswer.connectors.danswer_jira.connector.type", patched_type):
        yield


def test_fetch_jira_issues_batch_small_ticket(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small]

    docs, count = fetch_jira_issues_batch("project = TEST", 0, mock_jira_client)

    assert count == 1
    assert len(docs) == 1
    assert docs[0].id.endswith("/SMALL-1")
    assert "Small description" in docs[0].sections[0].text
    assert "Small comment 1" in docs[0].sections[0].text
    assert "Small comment 2" in docs[0].sections[0].text


def test_fetch_jira_issues_batch_large_ticket(
    mock_jira_client: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_large]

    docs, count = fetch_jira_issues_batch("project = TEST", 0, mock_jira_client)

    assert count == 1
    assert len(docs) == 0  # The large ticket should be skipped


def test_fetch_jira_issues_batch_mixed_tickets(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small, mock_issue_large]

    docs, count = fetch_jira_issues_batch("project = TEST", 0, mock_jira_client)

    assert count == 2
    assert len(docs) == 1  # Only the small ticket should be included
    assert docs[0].id.endswith("/SMALL-1")


@patch("danswer.connectors.danswer_jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 50)
def test_fetch_jira_issues_batch_custom_size_limit(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small, mock_issue_large]

    docs, count = fetch_jira_issues_batch("project = TEST", 0, mock_jira_client)

    assert count == 2
    assert len(docs) == 0  # Both tickets should be skipped due to the low size limit
