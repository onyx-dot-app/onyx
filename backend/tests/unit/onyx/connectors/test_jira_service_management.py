from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
import responses

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.client import JsmApiError, JsmClient
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


@pytest.fixture
def sample_requests_response() -> dict[str, Any]:
    return {
        "size": 2,
        "start": 0,
        "limit": 50,
        "isLastPage": True,
        "_links": {
            "base": "https://company.atlassian.net",
            "self": "https://company.atlassian.net/rest/servicedeskapi/request",
        },
        "values": [
            {
                "issueId": "1001",
                "issueKey": "IT-101",
                "serviceDeskId": "1",
                "createdDate": {
                    "epochMillis": 1700000000000,
                    "iso8601": "2023-11-14T22:13:20.000Z",
                },
                "currentStatus": {
                    "status": "In Progress",
                    "statusDate": {"epochMillis": 1700001000000},
                },
                "reporter": {
                    "displayName": "Alice Smith",
                    "emailAddress": "alice@example.com",
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Cannot connect to VPN"},
                    {
                        "fieldId": "description",
                        "value": "VPN client fails with TLS error.",
                    },
                ],
                "_links": {
                    "web": "https://company.atlassian.net/servicedesk/customer/portal/1/IT-101",
                },
            },
            {
                "issueId": "1002",
                "issueKey": "IT-102",
                "serviceDeskId": "1",
                "createdDate": {
                    "epochMillis": 1700002000000,
                    "iso8601": "2023-11-14T22:46:40.000Z",
                },
                "currentStatus": {
                    "status": "Resolved",
                    "statusDate": {"epochMillis": 1700003000000},
                },
                "reporter": {
                    "displayName": "Bob Jones",
                    "emailAddress": "bob@example.com",
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Request for new laptop monitor"},
                    {"fieldId": "description", "value": "Need a 27-inch 4K monitor."},
                ],
                "_links": {
                    "web": "https://company.atlassian.net/servicedesk/customer/portal/1/IT-102",
                },
            },
        ],
    }


@pytest.fixture
def sample_comments_response() -> dict[str, Any]:
    return {
        "values": [
            {
                "id": "501",
                "body": "Checked credentials, re-enabling certificate profile.",
                "author": {"displayName": "IT Support"},
                "public": True,
            },
            {
                "id": "502",
                "body": "Internal note: user has MFA reset required.",
                "author": {"displayName": "Tier 2 Agent"},
                "public": False,
            },
        ]
    }


def test_jsm_config_validation() -> None:
    config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net/",
        project_key="it",
        include_internal_comments=True,
    )
    assert config.jira_base_url == "https://company.atlassian.net"
    assert config.project_key == "it"
    assert config.include_internal_comments is True


def test_load_credentials_missing() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://company.atlassian.net"
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})


def test_load_credentials_valid() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://company.atlassian.net"
    )
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "secret123"}
    )
    assert connector.client is not None
    assert connector.client.base_url == "https://company.atlassian.net"


@responses.activate
def test_load_from_state(
    sample_requests_response: dict[str, Any],
    sample_comments_response: dict[str, Any],
) -> None:
    base_url = "https://company.atlassian.net"

    # Mock service desk endpoint
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/servicedesk",
        json={"values": [{"id": "1", "projectKey": "IT"}]},
        status=200,
    )

    # Mock requests endpoint
    # Mock servicedesk-scoped requests endpoint
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/servicedesk/1/request",
        json=sample_requests_response,
        status=200,
    )

    # Mock comments endpoint
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request/IT-101/comment",
        json=sample_comments_response,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request/IT-102/comment",
        json={"values": []},
        status=200,
    )

    connector = JiraServiceManagementConnector(
        jira_base_url=base_url,
        project_key="IT",
        include_internal_comments=True,
    )
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "token123"}
    )

    doc_batches = list(connector.load_from_state())
    assert len(doc_batches) == 1
    docs = doc_batches[0]
    assert len(docs) == 2

    # Verify first doc
    doc1 = docs[0]
    assert isinstance(doc1, Document)
    assert doc1.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc1.doc_created_at is not None
    assert doc1.doc_created_at.timestamp() == 1700000000
    assert doc1.semantic_identifier == "Cannot connect to VPN"
    assert doc1.metadata["status"] == "In Progress"
    assert doc1.metadata["ticket_id"] == "IT-101"
    assert doc1.metadata["reporter_email"] == "alice@example.com"
    assert doc1.primary_owners is not None
    assert doc1.primary_owners[0].display_name == "Alice Smith"

    # Verify comments and internal notes are present
    combined_text = "\n".join(
        s.text for s in doc1.sections if isinstance(s, TextSection)
    )
    assert "VPN client fails with TLS error." in combined_text
    assert "Public Comment by IT Support" in combined_text
    assert "Internal Note by Tier 2 Agent" in combined_text


@patch("time.sleep")
@responses.activate
def test_poll_source(
    mock_sleep: MagicMock, sample_requests_response: dict[str, Any]
) -> None:
    base_url = "https://company.atlassian.net"

    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request",
        json=sample_requests_response,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request/IT-101/comment",
        json={"values": []},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request/IT-102/comment",
        json={"values": []},
        status=200,
    )

    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "token123"}
    )

    # Filter range only covering IT-101 (updated at 1700001000), not IT-102 (1700003000)
    batches = list(connector.poll_source(start=1700000500, end=1700001500))
    assert len(batches) == 1
    polled_docs = batches[0]
    assert len(polled_docs) == 1
    doc = polled_docs[0]
    assert isinstance(doc, Document)
    assert doc.metadata["ticket_id"] == "IT-101"
    mock_sleep.assert_not_called()


@responses.activate
def test_retrieve_all_slim_docs(sample_requests_response: dict[str, Any]) -> None:
    base_url = "https://company.atlassian.net"

    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request",
        json=sample_requests_response,
        status=200,
    )

    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "token123"}
    )

    callback = create_autospec(IndexingHeartbeatInterface, instance=True)
    slim_batches = list(connector.retrieve_all_slim_docs(callback=callback))
    assert len(slim_batches) == 1
    slim_docs = slim_batches[0]
    assert len(slim_docs) == 2
    assert isinstance(slim_docs[0], SlimDocument)
    assert isinstance(slim_docs[1], SlimDocument)
    assert (
        slim_docs[0].id
        == "https://company.atlassian.net/servicedesk/customer/portal/1/IT-101"
    )
    assert (
        slim_docs[1].id
        == "https://company.atlassian.net/servicedesk/customer/portal/1/IT-102"
    )
    callback.progress.assert_called_once_with("jsm_retrieve_all_slim_docs", 2)


@patch("time.sleep")
@responses.activate
def test_client_retry_after(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"
    # First call returns 429 with Retry-After 1s, second returns 200
    responses.add(responses.GET, endpoint, status=429, headers={"Retry-After": "1"})
    responses.add(
        responses.GET,
        endpoint,
        json={"values": [{"id": "1", "projectKey": "IT"}]},
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    desks = client.get_service_desks()
    assert len(desks) == 1
    assert desks[0]["projectKey"] == "IT"
    assert len(responses.calls) == 2
    mock_sleep.assert_called_once_with(1)


@patch("time.sleep")
@responses.activate
def test_client_retry_after_http_date(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"
    # HTTP-date format for far future
    future_date = "Wed, 21 Oct 2099 07:28:00 GMT"
    responses.add(
        responses.GET, endpoint, status=429, headers={"Retry-After": future_date}
    )
    responses.add(
        responses.GET,
        endpoint,
        json={"values": [{"id": "1", "projectKey": "IT"}]},
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    desks = client.get_service_desks()
    assert len(desks) == 1
    # Capped at 60s
    mock_sleep.assert_called_once_with(60.0)


@patch("time.sleep")
@responses.activate
def test_client_retry_after_invalid_fallback(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"
    # Invalid format falls back to default backoff (2 * 1 = 2.0s)
    responses.add(
        responses.GET, endpoint, status=429, headers={"Retry-After": "invalid-date"}
    )
    responses.add(
        responses.GET,
        endpoint,
        json={"values": [{"id": "1", "projectKey": "IT"}]},
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    desks = client.get_service_desks()
    assert len(desks) == 1
    mock_sleep.assert_called_once_with(2.0)


@patch("time.sleep")
@responses.activate
def test_client_retry_after_exhausted_raises(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"
    for _ in range(3):
        responses.add(responses.GET, endpoint, status=429, headers={"Retry-After": "1"})

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    with pytest.raises(JsmApiError) as exc_info:
        client.get_service_desks()
    assert "Rate limited (429)" in str(exc_info.value)
    assert mock_sleep.call_count == 2


@patch("time.sleep")
@responses.activate
def test_poll_source_incremental_comment_and_early_filter(
    mock_sleep: MagicMock,
) -> None:
    base_url = "https://company.atlassian.net"

    # Request IT-201: statusDate in past (1700000000), but updatedDate in window (1700002000)
    # Request IT-202: statusDate and updatedDate in past (1700000000), outside window
    requests_data = {
        "size": 2,
        "start": 0,
        "limit": 50,
        "isLastPage": True,
        "values": [
            {
                "issueId": "2001",
                "issueKey": "IT-201",
                "serviceDeskId": "1",
                "createdDate": {"epochMillis": 1699999000000},
                "currentStatus": {
                    "status": "Open",
                    "statusDate": {"epochMillis": 1700000000000},
                },
                "updatedDate": {"epochMillis": 1700002000000},
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Updated by comment"}
                ],
                "_links": {"web": f"{base_url}/servicedesk/customer/portal/1/IT-201"},
            },
            {
                "issueId": "2002",
                "issueKey": "IT-202",
                "serviceDeskId": "1",
                "createdDate": {"epochMillis": 1699999000000},
                "currentStatus": {
                    "status": "Open",
                    "statusDate": {"epochMillis": 1700000000000},
                },
                "requestFieldValues": [{"fieldId": "summary", "value": "Old ticket"}],
                "_links": {"web": f"{base_url}/servicedesk/customer/portal/1/IT-202"},
            },
        ],
    }

    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request",
        json=requests_data,
        status=200,
    )
    # Only IT-201 comments should be requested; IT-202 must be skipped early before comment fetch
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request/IT-201/comment",
        json={
            "values": [
                {
                    "id": "99",
                    "body": "New comment",
                    "created": {"epochMillis": 1700002000000},
                }
            ]
        },
        status=200,
    )

    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "token123"}
    )

    # Polling window [1700001000, 1700003000]
    batches = list(connector.poll_source(start=1700001000, end=1700003000))
    assert len(batches) == 1
    docs = batches[0]
    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, Document)
    assert doc.metadata["ticket_id"] == "IT-201"
    assert doc.doc_created_at is not None
    assert doc.doc_updated_at is not None
    mock_sleep.assert_not_called()
    assert doc.doc_updated_at.timestamp() == 1700002000


@responses.activate
def test_comments_multi_page_pagination() -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/request/IT-200/comment"

    # Page 1: returns 2 comments, isLastPage=False
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": False,
            "values": [
                {"id": "1", "body": "Comment 1", "author": {"displayName": "User 1"}}
            ],
        },
        status=200,
    )
    # Page 2: returns 1 comment, isLastPage=True
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": True,
            "values": [
                {"id": "2", "body": "Comment 2", "author": {"displayName": "User 2"}}
            ],
        },
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    all_comments = client.get_request_comments("IT-200")
    assert len(all_comments) == 2
    assert all_comments[0]["body"] == "Comment 1"
    assert all_comments[1]["body"] == "Comment 2"
    assert len(responses.calls) == 2


@responses.activate
def test_get_customer_requests_service_desk_id_param() -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk/5/request"
    responses.add(
        responses.GET,
        endpoint,
        json={"values": []},
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    client.get_customer_requests(service_desk_id="5", search_term="printer")

    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call.request.url is not None
    assert "/rest/servicedeskapi/servicedesk/5/request" in call.request.url
    assert "requestOwnership" not in call.request.url
    assert "searchTerm=printer" in call.request.url


@responses.activate
def test_get_customer_requests_no_service_desk_id() -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/request"
    responses.add(
        responses.GET,
        endpoint,
        json={"values": []},
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    client.get_customer_requests(service_desk_id=None, search_term="printer")

    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call.request.url is not None
    assert "/rest/servicedeskapi/request?" in call.request.url
    assert "requestOwnership=ALL_REQUESTS" in call.request.url
    assert "searchTerm=printer" in call.request.url


@patch("time.sleep")
@responses.activate
def test_comments_error_raises_jsm_api_error(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/request/IT-200/comment"

    # Page 1: returns 1 comment, isLastPage=False
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": False,
            "values": [
                {"id": "1", "body": "Comment 1", "author": {"displayName": "User 1"}}
            ],
        },
        status=200,
    )
    # Page 2: returns 500 error for all attempts
    for _ in range(3):
        responses.add(responses.GET, endpoint, status=500)

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    with pytest.raises(JsmApiError):
        client.get_request_comments("IT-200")
    assert mock_sleep.call_count == 2


@responses.activate
def test_extract_request_document_reraises_jsm_api_error() -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/request/IT-300/comment"
    for _ in range(3):
        responses.add(responses.GET, endpoint, status=500)

    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    req = {
        "issueKey": "IT-300",
        "requestFieldValues": [{"fieldId": "summary", "value": "Test ticket"}],
    }
    with pytest.raises(JsmApiError):
        connector._extract_request_document(req, client)


def test_extract_request_document_handles_generic_exception() -> None:
    base_url = "https://company.atlassian.net"
    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    mock_client = MagicMock(spec=JsmClient)
    mock_client.get_request_comments.side_effect = RuntimeError("Unexpected issue")
    req = {
        "issueKey": "IT-301",
        "requestFieldValues": [
            {"fieldId": "summary", "value": "Generic exception ticket"}
        ],
    }
    doc = connector._extract_request_document(req, mock_client)
    assert doc is not None
    assert doc.semantic_identifier == "Generic exception ticket"


@responses.activate
def test_resolve_service_desk_id_pagination() -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"

    # Page 1: returns HR desk, isLastPage=False
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": False,
            "values": [{"id": "1", "projectKey": "HR"}],
        },
        status=200,
    )
    # Page 2: returns IT desk, isLastPage=True
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": True,
            "values": [{"id": "2", "projectKey": "IT"}],
        },
        status=200,
    )

    connector = JiraServiceManagementConnector(
        jira_base_url=base_url,
        project_key="IT",
    )
    connector.load_credentials(
        {"user_email": "admin@example.com", "api_token": "token123"}
    )
    client = connector._ensure_client()
    resolved_id = connector._resolve_service_desk_id(client)
    assert resolved_id == "2"
    assert connector.service_desk_id == "2"
