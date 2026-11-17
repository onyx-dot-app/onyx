from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)


@pytest.fixture
def jira_base_url() -> str:
    return "https://jsm.example.com"


@pytest.fixture
def project_key() -> str:
    return "SD"


@pytest.fixture
def mock_jira_operations() -> MagicMock:
    """A Server / Data Center Jira gateway. Set ``_is_cloud.return_value`` to
    True for the Cloud search path."""
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = False
    return gateway


@pytest.fixture
def mock_jsm_operations() -> MagicMock:
    return create_autospec(JiraServiceManagementSourceOperations, instance=True)


@pytest.fixture
def jsm_connector(
    jira_base_url: str,
    project_key: str,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
    )
    connector._source_operations = mock_jira_operations
    connector._jsm_operations = mock_jsm_operations
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_issue() -> Callable[..., dict[str, Any]]:
    def _create_mock_issue(
        key: str = "SD-1",
        summary: str = "Cannot log in",
        updated: str = "2023-01-01T12:00:00.000+0000",
        created: str = "2023-01-01T11:00:00.000+0000",
        description: Any = "I forgot my password",
        labels: list[str] | None = None,
        project_key: str = "SD",
        project_name: str = "Service Desk",
        issuetype_name: str = "Service Request",
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
                "displayName": "Test Reporter",
                "emailAddress": "reporter@example.com",
            },
            "assignee": {
                "displayName": "Test Agent",
                "emailAddress": "agent@example.com",
            },
            "priority": {"name": "High"},
            "status": {"name": "Open"},
            "resolution": None,
            "project": {"key": project_key, "name": project_name},
            "issuetype": {"name": issuetype_name},
            "comment": {"comments": comments or []},
        }
        return {"id": key.split("-")[-1], "key": key, "fields": fields}

    return _create_mock_issue
