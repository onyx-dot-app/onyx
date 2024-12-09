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
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "Small description"
    fields.comment = MagicMock()
    fields.comment.comments = [
        MagicMock(body="Small comment 1"),
        MagicMock(body="Small comment 2"),
    ]
    fields.creator = MagicMock()
    fields.creator.displayName = "John Doe"
    fields.creator.emailAddress = "john@example.com"
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
    fields.creator = MagicMock()
    fields.creator.displayName = "Jane Doe"
    fields.creator.emailAddress = "jane@example.com"
    fields.summary = "Large Issue"
    fields.updated = "2023-01-02T00:00:00+0000"
    fields.labels = []

    issue.fields = fields
    issue.key = "LARGE-1"
    return issue


@pytest.fixture
def mock_jira_api_version() -> Generator[Any, Any, Any]:
    with patch("danswer.connectors.danswer_jira.connector.JIRA_API_VERSION", "2"):
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

    docs = list(fetch_jira_issues_batch(mock_jira_client, "project = TEST", 50))

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

    docs = list(fetch_jira_issues_batch(mock_jira_client, "project = TEST", 50))

    assert len(docs) == 0  # The large ticket should be skipped


def test_fetch_jira_issues_batch_mixed_tickets(
    mock_jira_client: MagicMock,
    mock_issue_small: MagicMock,
    mock_issue_large: MagicMock,
    patched_environment: MockFixture,
) -> None:
    mock_jira_client.search_issues.return_value = [mock_issue_small, mock_issue_large]

    docs = list(fetch_jira_issues_batch(mock_jira_client, "project = TEST", 50))

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

    docs = list(fetch_jira_issues_batch(mock_jira_client, "project = TEST", 50))

    assert len(docs) == 0  # Both tickets should be skipped due to the low size limit
