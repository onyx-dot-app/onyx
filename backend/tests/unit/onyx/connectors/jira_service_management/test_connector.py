from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    process_service_desk_request,
)
from onyx.connectors.jira_service_management.utils import (
    build_customer_portal_url,
    get_current_status_name,
    get_request_type_name,
)


def _mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock._options = {"server": "https://jira.example.com", "rest_api_version": "2"}
    mock._session = MagicMock()
    mock._get_url = MagicMock(
        side_effect=lambda path: f"https://jira.example.com/rest/api/2/{path}"
    )
    return mock


def _make_raw_issue(issue_id: str = "1", key: str = "HELP-1") -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": "Printer is broken",
            "description": "The printer on floor 2 is jammed.",
            "labels": [],
            "created": "2024-01-01T00:00:00.000+0000",
            "updated": "2024-01-02T00:00:00.000+0000",
            "status": {"name": "Open"},
            "project": {"key": "HELP", "name": "Help Desk"},
            "issuetype": {"name": "Service Request"},
            "comment": {"comments": []},
        },
    }


def _make_issue(client: MagicMock, key: str = "HELP-1") -> Issue:
    return Issue(client._options, client._session, raw=_make_raw_issue(key=key))


def _mock_request_response() -> dict[str, Any]:
    return {
        "issueId": "1",
        "issueKey": "HELP-1",
        "requestType": {"id": "4", "name": "Get IT help"},
        "serviceDeskId": "3",
        "channel": "portal",
        "currentStatus": {
            "status": "Waiting for support",
            "statusCategory": "NEW",
        },
    }


def test_process_service_desk_request_adds_jsm_metadata() -> None:
    client = _mock_jira_client()
    resp = MagicMock()
    resp.json.return_value = _mock_request_response()
    client._session.get.return_value = resp

    doc = process_service_desk_request(
        jira_client=client,
        jira_base_url="https://jira.example.com",
        issue=_make_issue(client),
    )

    assert doc is not None
    assert doc.source == "jira_service_management"
    assert doc.metadata["request_type"] == "Get IT help"
    assert doc.metadata["request_status"] == "Waiting for support"
    assert doc.metadata["channel"] == "portal"
    assert doc.metadata["service_desk_id"] == "3"
    assert doc.metadata["customer_portal_url"] == (
        "https://jira.example.com/servicedesk/customer/portal/3/HELP-1"
    )
    # doc id is the browse URL plus the JSM marker so it does not collide
    # with a document indexed through the plain Jira connector
    assert doc.id == ("https://jira.example.com/browse/HELP-1#jira-service-management")


def test_process_service_desk_request_without_jsm_view() -> None:
    """Issues not exposed as customer requests still index as documents."""
    client = _mock_jira_client()
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404", response=resp
    )
    client._session.get.return_value = resp

    doc = process_service_desk_request(
        jira_client=client,
        jira_base_url="https://jira.example.com",
        issue=_make_issue(client),
    )

    assert doc is not None
    assert doc.source == "jira_service_management"
    assert "request_type" not in doc.metadata


def test_load_credentials_resolves_project_from_service_desk() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        service_desk_id=3,
    )
    with (
        patch(
            "onyx.connectors.jira_service_management.connector.build_jira_client"
        ) as mock_build,
        patch(
            "onyx.connectors.jira_service_management.connector.find_service_desk"
        ) as mock_find,
    ):
        mock_build.return_value = _mock_jira_client()
        mock_find.return_value = {"id": "3", "projectKey": "HELP"}

        connector.load_credentials({"jira_api_token": "tok"})

    assert connector.jira_project == "HELP"


def test_load_credentials_unresolved_service_desk_fails() -> None:
    """An unresolvable service desk id must not fall back to an unscoped sync."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        service_desk_id=99,
    )
    with (
        patch(
            "onyx.connectors.jira_service_management.connector.build_jira_client"
        ) as mock_build,
        patch(
            "onyx.connectors.jira_service_management.connector.find_service_desk",
            return_value=None,
        ),
    ):
        mock_build.return_value = _mock_jira_client()
        with pytest.raises(ConnectorValidationError):
            connector.load_credentials({"jira_api_token": "tok"})


def test_jql_query_scoped_to_project() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="HELP",
    )
    jql = connector._get_jql_query(1000, 2000)
    assert 'project = "HELP"' in jql
    assert "updated >= 1000000" in jql
    assert "updated <= 2000000" in jql


def test_validate_connector_settings_unknown_project() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="NOPE",
    )
    connector._jira_client = _mock_jira_client()
    with patch(
        "onyx.connectors.jira_service_management.connector.find_service_desk",
        return_value=None,
    ):
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()


def test_validate_connector_settings_service_desk_found() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="HELP",
    )
    connector._jira_client = _mock_jira_client()
    with patch(
        "onyx.connectors.jira_service_management.connector.find_service_desk",
        return_value={"id": "3", "projectKey": "HELP"},
    ):
        connector.validate_connector_settings()


def test_request_helpers() -> None:
    request = _mock_request_response()
    assert get_request_type_name(request) == "Get IT help"
    assert get_current_status_name(request) == "Waiting for support"
    assert get_request_type_name(None) is None
    assert get_current_status_name({}) is None
    assert (
        build_customer_portal_url("https://jira.example.com", "3", "HELP-1")
        == "https://jira.example.com/servicedesk/customer/portal/3/HELP-1"
    )
    assert build_customer_portal_url("https://jira.example.com", None, "H-1") is None
