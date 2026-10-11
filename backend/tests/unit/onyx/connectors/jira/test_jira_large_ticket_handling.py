from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.jira.connector import _perform_jql_search, process_jira_issue


@pytest.fixture
def mock_issue_small(
    create_mock_issue: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return create_mock_issue(
        key="SMALL-1",
        summary="Small Issue",
        description="Small description",
        comments=[{"body": "Small comment 1"}, {"body": "Small comment 2"}],
    )


@pytest.fixture
def mock_issue_large(
    create_mock_issue: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return create_mock_issue(
        key="LARGE-1",
        summary="Large Issue",
        description="a" * 99_000,
        comments=[
            {"body": "Large comment " * 1000},
            {"body": "Another large comment " * 1000},
        ],
    )


def test_fetch_jira_issues_batch_small_ticket(
    mock_source_operations: MagicMock,
    mock_issue_small: dict[str, Any],
) -> None:
    mock_source_operations.search_issues.return_value = [mock_issue_small]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_source_operations, "project = TEST", 0, 50))
    assert len(issues) == 1

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 1
    doc = docs[0]
    assert doc is not None  # for type-checking
    assert doc.id.endswith("/SMALL-1")
    assert doc.sections[0].text is not None
    assert "Small description" in doc.sections[0].text
    assert "Small comment 1" in doc.sections[0].text
    assert "Small comment 2" in doc.sections[0].text


def test_fetch_jira_issues_batch_large_ticket(
    mock_source_operations: MagicMock,
    mock_issue_large: dict[str, Any],
) -> None:
    mock_source_operations.search_issues.return_value = [mock_issue_large]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_source_operations, "project = TEST", 0, 50))
    assert len(issues) == 1

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 0  # The large ticket should be skipped


def test_fetch_jira_issues_batch_mixed_tickets(
    mock_source_operations: MagicMock,
    mock_issue_small: dict[str, Any],
    mock_issue_large: dict[str, Any],
) -> None:
    mock_source_operations.search_issues.return_value = [
        mock_issue_small,
        mock_issue_large,
    ]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_source_operations, "project = TEST", 0, 50))
    assert len(issues) == 2

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 1  # Only the small ticket should be included
    doc = docs[0]
    assert doc is not None  # for type-checking
    assert doc.id.endswith("/SMALL-1")


@patch("onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 50)
def test_fetch_jira_issues_batch_custom_size_limit(
    mock_source_operations: MagicMock,
    mock_issue_small: dict[str, Any],
    mock_issue_large: dict[str, Any],
) -> None:
    mock_source_operations.search_issues.return_value = [
        mock_issue_small,
        mock_issue_large,
    ]

    # First get the issues via pagination
    issues = list(_perform_jql_search(mock_source_operations, "project = TEST", 0, 50))
    assert len(issues) == 2

    # Then process each issue
    docs = [process_jira_issue("test.com", issue) for issue in issues]
    docs = [doc for doc in docs if doc is not None]  # Filter out None values

    assert len(docs) == 0  # Both tickets should be skipped due to the low size limit
