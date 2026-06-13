from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests import Response

from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument


@pytest.fixture
def mock_heartbeat() -> MagicMock:
    heartbeat = MagicMock(spec=IndexingHeartbeatInterface)
    heartbeat.should_stop.return_value = False
    return heartbeat


def test_jsm_connector_init_success() -> None:
    connector = JiraServiceManagementConnector(
        jira_url="http://test-jira.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
        service_desk_id="1",
    )
    assert connector.jira_url == "http://test-jira.atlassian.net"
    assert connector.jira_user_email == "test@example.com"
    assert connector.jira_api_token == "test-token"
    assert connector.service_desk_id == "1"


def test_jsm_connector_init_url_format() -> None:
    connector = JiraServiceManagementConnector(
        jira_url="test-jira.atlassian.net/",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )
    assert connector.jira_url == "https://test-jira.atlassian.net"


def test_jsm_connector_init_missing_credentials() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        JiraServiceManagementConnector(
            jira_url="", jira_user_email="test@example.com", jira_api_token="test-token"
        )


def test_get_service_desks_configured() -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
        service_desk_id="42",
    )
    assert connector._get_service_desks() == ["42"]


@patch("requests.get")
def test_get_service_desks_discovery(mock_get: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    # Mock response containing a list of service desks
    mock_resp = MagicMock(spec=Response)
    mock_resp.json.return_value = {
        "values": [
            {"id": 10, "projectName": "Desk A"},
            {"id": 20, "projectName": "Desk B"},
        ],
        "isLastPage": True,
    }
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    desks = connector._get_service_desks()
    assert desks == ["10", "20"]
    mock_get.assert_called_once()


@patch("requests.post")
def test_get_customer_requests(mock_post: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    mock_resp = MagicMock(spec=Response)
    mock_resp.json.return_value = {
        "values": [{"issueKey": "JSM-1"}, {"issueKey": "JSM-2"}],
        "isLastPage": True,
    }
    mock_post.return_value = mock_resp

    batches = list(connector._get_customer_requests(service_desk_id="10", start_time=0))
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert batches[0][0]["issueKey"] == "JSM-1"

    mock_post.assert_called_once()
    # verify JQL query
    called_json = mock_post.call_args[1]["json"]
    assert "serviceDesk = 10" in called_json["jql"]


@patch("requests.post")
def test_retrieve_all_slim_docs(mock_post: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
        service_desk_id="10",
    )

    mock_post_resp = MagicMock(spec=Response)
    mock_post_resp.json.return_value = {
        "values": [
            {
                "issueKey": "JSM-1",
                "createdDate": {"epochMillis": 1600000000000},  # within range
            },
            {
                "issueKey": "JSM-2",
                "createdDate": {
                    "epochMillis": 1800000000000
                },  # after end (end is 1700000000)
            },
        ],
        "isLastPage": True,
    }
    mock_post.return_value = mock_post_resp

    slim_docs = list(connector.retrieve_all_slim_docs(start=1500000000, end=1700000000))
    assert len(slim_docs) == 1
    assert isinstance(slim_docs[0], SlimDocument)
    assert slim_docs[0].id == "JSM-1"


@patch("requests.get")
def test_fetch_request_comments(mock_get: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    mock_resp = MagicMock(spec=Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "values": [{"body": "Hello comment 1"}, {"body": "Hello comment 2"}],
        "isLastPage": True,
    }
    mock_get.return_value = mock_resp

    comments = connector._fetch_request_comments("JSM-1")
    assert comments == ["Hello comment 1", "Hello comment 2"]
    mock_get.assert_called_once_with(
        "https://test.atlassian.net/rest/servicedeskapi/request/JSM-1/comment",
        auth=connector.auth,
        headers=connector.headers,
        params={"start": 0, "limit": 500},
    )


@patch("requests.get")
def test_retrieve_docs(mock_get: MagicMock, mock_heartbeat: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    # We will fetch details for JSM-1. The method first does requests.get for the request details,
    # then call _fetch_request_comments which does requests.get for comments.
    def get_side_effect(url: str, *_args: Any, **_kwargs: Any) -> Response:
        resp = MagicMock(spec=Response)
        resp.status_code = 200
        if "comment" in url:
            resp.json.return_value = {
                "values": [{"body": "Comment text"}],
                "isLastPage": True,
            }
        else:
            resp.json.return_value = {
                "summary": "Fix login issue",
                "description": "User cannot login",
                "createdDate": {"epochMillis": 1600000000000},
                "currentStatus": {"status": "In Progress"},
                "requestType": {"name": "Incident"},
            }
        return resp

    mock_get.side_effect = get_side_effect

    slim_doc = SlimDocument(id="JSM-1")
    docs = list(connector.retrieve_docs([slim_doc], mock_heartbeat))

    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, Document)
    assert doc.id == "JSM-1"
    assert doc.title == "[JSM-1] Fix login issue"
    assert len(doc.sections) == 2
    assert doc.sections[0].text == "User cannot login"
    assert doc.sections[1].text == "Comment text"
    assert (
        doc.metadata["service_desk_id"] == "unknown"
    )  # mock get_side_effect doesn't return serviceDeskId
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["request_type"] == "Incident"


@patch("requests.get")
def test_retrieve_docs_not_found(
    mock_get: MagicMock, mock_heartbeat: MagicMock
) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    mock_resp = MagicMock(spec=Response)
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    slim_doc = SlimDocument(id="JSM-1")
    docs = list(connector.retrieve_docs([slim_doc], mock_heartbeat))

    assert len(docs) == 0


@patch("requests.get")
def test_retrieve_docs_failure(mock_get: MagicMock, mock_heartbeat: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    mock_get.side_effect = RuntimeError("Connection timed out")

    slim_doc = SlimDocument(id="JSM-1")
    docs = list(connector.retrieve_docs([slim_doc], mock_heartbeat))

    assert len(docs) == 1
    assert isinstance(docs[0], ConnectorFailure)
    assert docs[0].failed_document is not None
    assert docs[0].failed_document.document_id == "JSM-1"
    assert "Connection timed out" in docs[0].failure_message


def test_checkpoint_roundtrip() -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )
    checkpoint = connector.build_dummy_checkpoint()
    assert checkpoint.has_more is False
    restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    assert restored.has_more == checkpoint.has_more


@patch("requests.get")
@patch("requests.post")
def test_load_from_checkpoint(mock_post: MagicMock, mock_get: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
        service_desk_id="10",
    )

    # Mock retrieve_all_slim_docs request
    mock_post_resp = MagicMock(spec=Response)
    mock_post_resp.json.return_value = {
        "values": [
            {"issueKey": "JSM-1", "createdDate": {"epochMillis": 1600000000000}}
        ],
        "isLastPage": True,
    }
    mock_post.return_value = mock_post_resp

    # Mock retrieve_docs requests
    def get_side_effect(url: str, *_args: Any, **_kwargs: Any) -> Response:
        resp = MagicMock(spec=Response)
        resp.status_code = 200
        if "comment" in url:
            resp.json.return_value = {
                "values": [{"body": "Comment text"}],
                "isLastPage": True,
            }
        else:
            resp.json.return_value = {
                "summary": "Fix login issue",
                "description": "User cannot login",
                "createdDate": {"epochMillis": 1600000000000},
                "currentStatus": {"status": "In Progress"},
                "requestType": {"name": "Incident"},
                "serviceDeskId": "10",
            }
        return resp

    mock_get.side_effect = get_side_effect

    checkpoint = connector.build_dummy_checkpoint()
    generator = connector.load_from_checkpoint(
        start=1500000000, end=1700000000, checkpoint=checkpoint
    )

    docs = list(generator)
    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].id == "JSM-1"
    assert docs[0].metadata["service_desk_id"] == "10"


@patch("requests.get")
def test_fetch_request_comments_filtering(mock_get: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_url="https://test.atlassian.net",
        jira_user_email="test@example.com",
        jira_api_token="test-token",
    )

    mock_resp = MagicMock(spec=Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "values": [
            {"body": "Hello public comment", "public": True},
            {"body": "Hello private comment", "public": False},
            {"body": "Hello default public comment"},
        ],
        "isLastPage": True,
    }
    mock_get.return_value = mock_resp

    comments = connector._fetch_request_comments("JSM-1")
    assert comments == ["Hello public comment", "Hello default public comment"]
