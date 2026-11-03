from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraSourceOperations


@pytest.fixture
def jira_base_url() -> str:
    return "https://jira.example.com"


@pytest.fixture
def project_key() -> str:
    return "TEST"


@pytest.fixture
def user_email() -> str:
    return "test@example.com"


@pytest.fixture
def mock_jira_api_token() -> str:
    return "token123"


@pytest.fixture
def mock_source_operations() -> MagicMock:
    """A Server / Data Center gateway. Set ``_is_cloud.return_value`` to True
    for the Cloud search path."""
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = False
    return gateway


@pytest.fixture
def jira_connector(
    jira_base_url: str, project_key: str, mock_source_operations: MagicMock
) -> Generator[JiraConnector, None, None]:
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        comment_email_blacklist=["blacklist@example.com"],
        labels_to_skip=["secret", "sensitive"],
    )
    connector._source_operations = mock_source_operations
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_issue() -> Callable[..., dict[str, Any]]:
    def _create_mock_issue(
        key: str = "TEST-123",
        summary: str = "Test Issue",
        updated: str = "2023-01-01T12:00:00.000+0000",
        created: str = "2023-01-01T12:00:00.000+0000",
        description: Any = "Test Description",
        labels: list[str] | None = None,
        project_key: str = "TEST",
        project_name: str = "Test Project",
        issuetype_name: str = "Story",
        parent_key: str | None = None,
        parent_issuetype_name: str | None = None,
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """A raw issue as the Jira REST API returns it."""
        fields: dict[str, Any] = {
            "summary": summary,
            "updated": updated,
            "created": created,
            "description": description,
            "labels": labels or [],
            "reporter": {
                "displayName": "Test Creator",
                "emailAddress": "creator@example.com",
            },
            "assignee": {
                "displayName": "Test Assignee",
                "emailAddress": "assignee@example.com",
            },
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "resolution": {"name": "Fixed"},
            "project": {"key": project_key, "name": project_name},
            "issuetype": {"name": issuetype_name},
            "parent": (
                {
                    "key": parent_key,
                    "fields": {
                        "summary": f"Parent {parent_key}",
                        "issuetype": {"name": parent_issuetype_name or "Story"},
                    },
                }
                if parent_key
                else None
            ),
            "comment": {"comments": comments or []},
        }
        return {"id": key.split("-")[-1], "key": key, "fields": fields}

    return _create_mock_issue
