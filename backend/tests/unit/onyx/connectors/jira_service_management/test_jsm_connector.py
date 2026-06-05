from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document


def _mock_jira_client() -> MagicMock:
    mock = MagicMock()
    mock._options = {"server": "https://jsm.example.com", "rest_api_version": "3"}
    mock._session = MagicMock()
    mock._get_url = lambda path: f"https://jsm.example.com/rest/servicedeskapi/{path}"
    return mock


def test_get_service_desk_id_by_key() -> None:
    client = _mock_jira_client()
    resp = MagicMock()
    resp.json.return_value = {"id": "123"}
    client._session.get.return_value = resp

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com", project_key="TEST"
    )
    connector._jira_client = client

    desk_id = connector._get_service_desk_id_by_key("TEST")
    assert desk_id == "123"
    client._session.get.assert_called_once_with(
        "https://jsm.example.com/rest/servicedeskapi/servicedesk/TEST"
    )


def test_fetch_jsm_comments() -> None:
    client = _mock_jira_client()
    resp = MagicMock()
    resp.json.return_value = {
        "values": [
            {
                "id": "1",
                "body": "Comment 1",
                "author": {"emailAddress": "user@test.com"},
                "created": {"iso8601": "2026-06-05T00:00:00.000Z"},
            },
            {
                "id": "2",
                "body": "Comment 2",
                "author": {"emailAddress": "bot@test.com"},
                "created": {"iso8601": "2026-06-05T01:00:00.000Z"},
            },
        ],
        "isLastPage": True,
    }
    client._session.get.return_value = resp

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com",
        comment_email_blacklist=["bot@test.com"],
    )
    connector._jira_client = client

    comments = connector._fetch_jsm_comments("TEST-1")
    assert len(comments) == 2
    assert comments[0]["body"] == "Comment 1"


def test_load_from_checkpoint() -> None:
    client = _mock_jira_client()

    desk_resp = MagicMock()
    desk_resp.json.return_value = {"id": "123"}

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [
            {
                "issueKey": "TEST-1",
                "createdDate": {"iso8601": "2026-06-05T00:00:00.000Z"},
                "currentStatus": {
                    "status": "In Progress",
                    "statusDate": {"iso8601": "2026-06-05T00:30:00.000Z"},
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Test Summary"},
                    {"fieldId": "description", "value": "Test Description"},
                ],
                "reporter": {
                    "displayName": "Reporter Name",
                    "emailAddress": "reporter@test.com",
                },
                "_links": {
                    "web": "https://jsm.example.com/servicedesk/customer/portal/1/TEST-1"
                },
            }
        ],
        "isLastPage": True,
    }

    comments_resp = MagicMock()
    comments_resp.json.return_value = {
        "values": [
            {
                "id": "1",
                "body": "Hello",
                "author": {"emailAddress": "user@test.com"},
                "created": {"iso8601": "2026-06-05T01:00:00.000Z"},
            }
        ],
        "isLastPage": True,
    }

    def session_get_side_effect(url: str, *args: Any, **kwargs: Any) -> MagicMock:
        if "servicedesk/TEST" in url:
            return desk_resp
        elif "request/TEST-1/comment" in url:
            return comments_resp
        elif "request" in url:
            return req_resp
        raise ValueError(f"Unexpected URL: {url}")

    client._session.get.side_effect = session_get_side_effect

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com",
        project_key="TEST",
        comment_email_blacklist=["bot@test.com"],
    )
    connector._jira_client = client

    checkpoint = JiraConnectorCheckpoint(has_more=True)
    start_ts = datetime(2026, 6, 4, tzinfo=timezone.utc).timestamp()
    end_ts = datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()

    docs = list(connector.load_from_checkpoint(start_ts, end_ts, checkpoint))
    assert len(docs) == 2

    doc = docs[1]
    assert isinstance(doc, Document)
    assert doc.id == "https://jsm.example.com/servicedesk/customer/portal/1/TEST-1"
    assert "Test Description" in doc.sections[0].text
    assert "Comment: Hello" in doc.sections[0].text
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.title == "TEST-1 Test Summary"


def test_load_from_checkpoint_date_filtering() -> None:
    client = _mock_jira_client()

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [
            {
                "issueKey": "TEST-1",
                "createdDate": {"iso8601": "2026-06-05T00:00:00.000Z"},
                "currentStatus": {
                    "status": "In Progress",
                    "statusDate": {"iso8601": "2026-06-05T00:30:00.000Z"},
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Test Summary 1"},
                    {"fieldId": "description", "value": "Test Description 1"},
                ],
                "_links": {
                    "web": "https://jsm.example.com/servicedesk/customer/portal/1/TEST-1"
                },
            },
            {
                "issueKey": "TEST-2",
                "createdDate": {"iso8601": "2026-06-01T00:00:00.000Z"},
                "currentStatus": {
                    "status": "Closed",
                    "statusDate": {"iso8601": "2026-06-01T00:30:00.000Z"},
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Test Summary 2"},
                    {"fieldId": "description", "value": "Test Description 2"},
                ],
            },
        ],
        "isLastPage": True,
    }

    comments_resp = MagicMock()
    comments_resp.json.return_value = {"values": [], "isLastPage": True}

    def session_get_side_effect(url: str, *args: Any, **kwargs: Any) -> MagicMock:
        if "comment" in url:
            return comments_resp
        return req_resp

    client._session.get.side_effect = session_get_side_effect

    connector = JiraServiceManagementConnector(jira_base_url="https://jsm.example.com")
    connector._jira_client = client

    checkpoint = JiraConnectorCheckpoint(has_more=True)
    start_ts = datetime(2026, 6, 4, tzinfo=timezone.utc).timestamp()
    end_ts = datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()

    docs = list(connector.load_from_checkpoint(start_ts, end_ts, checkpoint))
    assert len(docs) == 2
    assert isinstance(docs[1], Document)
    assert docs[1].title == "TEST-1 Test Summary 1"


def test_validate_connector_settings_success() -> None:
    client = _mock_jira_client()
    resp = MagicMock()
    resp.json.return_value = {"id": "123"}
    client._session.get.return_value = resp

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com", project_key="TEST"
    )
    connector._jira_client = client

    connector.validate_connector_settings()


def test_validate_connector_settings_failure() -> None:
    client = _mock_jira_client()
    client._session.get.side_effect = Exception("HTTP 404 Not Found")

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com", project_key="TEST"
    )
    connector._jira_client = client

    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()
