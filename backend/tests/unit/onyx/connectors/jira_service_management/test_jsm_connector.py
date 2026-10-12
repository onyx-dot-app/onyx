"""Unit tests for the Jira Service Management connector: JQL scoping and
Service Desk metadata enrichment, with the source gateway mocked."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)

_BASE_URL = "https://example.atlassian.net"


def _issue(key: str = "SD-1") -> dict[str, Any]:
    """Smallest raw issue ``process_jira_issue`` can turn into a Document."""
    return {
        "key": key,
        "fields": {
            "summary": "VPN access request",
            "description": "I need VPN access",
            "comment": {"comments": []},
            "reporter": {
                "displayName": "Jane Doe",
                "emailAddress": "jane@example.com",
            },
            "assignee": None,
            "priority": {"name": "High"},
            "status": {"name": "Waiting for support"},
            "resolution": None,
            "labels": [],
            "created": "2025-01-01T00:00:00.000+0000",
            "updated": "2025-01-02T00:00:00.000+0000",
            "duedate": None,
            "issuetype": {"name": "IT Help"},
            "project": {"key": "SD", "name": "Service Desk"},
        },
    }


def _connector(**kwargs: Any) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(jira_base_url=_BASE_URL, **kwargs)
    connector._source_operations = MagicMock()
    return connector


def test_jql_scopes_project_to_service_desk() -> None:
    connector = _connector(project_key="SD")
    jql = connector._get_jql_query(1000, 2000)

    assert "projectType = service_desk" in jql
    assert 'project = "SD"' in jql


def test_jql_scopes_everything_to_service_desk() -> None:
    connector = _connector()
    jql = connector._get_jql_query(1000, 2000)

    assert "projectType = service_desk" in jql
    assert "project =" not in jql


def test_jql_custom_query_passthrough() -> None:
    connector = _connector(jql_query='project = "SD" AND issuetype = "IT Help"')
    jql = connector._get_jql_query(1000, 2000)

    assert 'project = "SD" AND issuetype = "IT Help"' in jql
    # custom JQL is the escape hatch: no projectType filter is added
    assert "projectType" not in jql


def test_process_issue_sets_jsm_source_and_metadata() -> None:
    connector = _connector(project_key="SD")
    connector.source_operations.get_service_desk_request.return_value = {
        "issueKey": "SD-1",
        "serviceDeskId": "7",
        "requestTypeId": "42",
        "currentStatus": {"status": "Waiting for customer"},
        "_links": {
            "web": "https://example.atlassian.net/servicedesk/customer/portal/7/SD-1"
        },
    }

    document = connector._process_issue(_issue(), None)

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.metadata["service_desk_status"] == "Waiting for customer"
    assert document.metadata["service_desk_id"] == "7"
    assert document.metadata["request_type_id"] == "42"
    assert document.metadata["customer_portal_link"].endswith("/portal/7/SD-1")
    connector.source_operations.get_service_desk_request.assert_called_once_with(
        issue_key="SD-1"
    )


def test_process_issue_non_request_indexes_without_jsm_fields() -> None:
    connector = _connector(project_key="SD")
    connector.source_operations.get_service_desk_request.return_value = None

    document = connector._process_issue(_issue(), None)

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "service_desk_status" not in document.metadata
    assert "customer_portal_link" not in document.metadata


def test_process_issue_surfaces_api_errors() -> None:
    from onyx.connectors.jira.source_operations import JiraApiError

    connector = _connector(project_key="SD")
    connector.source_operations.get_service_desk_request.side_effect = JiraApiError(
        "forbidden", status_code=403, text=None
    )

    with pytest.raises(JiraApiError):
        connector._process_issue(_issue(), None)
