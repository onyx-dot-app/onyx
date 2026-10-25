import time
from unittest.mock import MagicMock, create_autospec, patch
import pytest
import responses
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.client import JsmClient, JsmApiError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document, SlimDocument


@pytest.fixture
def sample_requests_response():
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
                    {"fieldId": "description", "value": "VPN client fails with TLS error."},
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
def sample_comments_response():
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


def test_jsm_config_validation():
    config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net/",
        project_key="it",
        include_internal_comments=True,
    )
    assert config.jira_base_url == "https://company.atlassian.net"
    assert config.project_key == "it"
    assert config.include_internal_comments is True


def test_load_credentials_missing():
    connector = JiraServiceManagementConnector(jira_base_url="https://company.atlassian.net")
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})


def test_load_credentials_valid():
    connector = JiraServiceManagementConnector(jira_base_url="https://company.atlassian.net")
    connector.load_credentials({"user_email": "admin@example.com", "api_token": "secret123"})
    assert connector.client is not None
    assert connector.client.base_url == "https://company.atlassian.net"


@responses.activate
def test_load_from_state(sample_requests_response, sample_comments_response):
    base_url = "https://company.atlassian.net"

    # Mock service desk endpoint
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/servicedesk",
        json={"values": [{"id": "1", "projectKey": "IT"}]},
        status=200,
    )

    # Mock requests endpoint
    # Mock requests endpoint (standard JSM endpoint with serviceDeskId filter)
    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request",
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
    connector.load_credentials({"user_email": "admin@example.com", "api_token": "token123"})

    doc_batches = list(connector.load_from_state())
    assert len(doc_batches) == 1
    docs = doc_batches[0]
    assert len(docs) == 2

    # Verify first doc
    doc1 = docs[0]
    assert isinstance(doc1, Document)
    assert doc1.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc1.semantic_identifier == "Cannot connect to VPN"
    assert doc1.metadata["status"] == "In Progress"
    assert doc1.metadata["ticket_id"] == "IT-101"
    assert doc1.metadata["reporter_email"] == "alice@example.com"
    assert doc1.primary_owners[0].display_name == "Alice Smith"

    # Verify comments and internal notes are present
    combined_text = "\n".join(s.text for s in doc1.sections)
    assert "VPN client fails with TLS error." in combined_text
    assert "Public Comment by IT Support" in combined_text
    assert "Internal Note by Tier 2 Agent" in combined_text


@responses.activate
def test_poll_source(sample_requests_response):
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
    connector.load_credentials({"user_email": "admin@example.com", "api_token": "token123"})

    # Filter range only covering IT-101 (updated at 1700001000), not IT-102 (1700003000)
    batches = list(connector.poll_source(start=1700000500, end=1700001500))
    assert len(batches) == 1
    polled_docs = batches[0]
    assert len(polled_docs) == 1
    assert polled_docs[0].metadata["ticket_id"] == "IT-101"


@responses.activate
def test_retrieve_all_slim_docs(sample_requests_response):
    base_url = "https://company.atlassian.net"

    responses.add(
        responses.GET,
        f"{base_url}/rest/servicedeskapi/request",
        json=sample_requests_response,
        status=200,
    )

    connector = JiraServiceManagementConnector(jira_base_url=base_url)
    connector.load_credentials({"user_email": "admin@example.com", "api_token": "token123"})

    callback = create_autospec(IndexingHeartbeatInterface, instance=True)
    slim_batches = list(connector.retrieve_all_slim_docs(callback=callback))
    assert len(slim_batches) == 1
    slim_docs = slim_batches[0]
    assert len(slim_docs) == 2
    assert isinstance(slim_docs[0], SlimDocument)
    assert slim_docs[0].id == "https://company.atlassian.net/servicedesk/customer/portal/1/IT-101"
    assert slim_docs[1].id == "https://company.atlassian.net/servicedesk/customer/portal/1/IT-102"
    callback.progress.assert_called_once_with("jsm_retrieve_all_slim_docs", 2)


@patch("time.sleep")
@responses.activate
def test_client_retry_after(mock_sleep: MagicMock) -> None:
    base_url = "https://company.atlassian.net"
    endpoint = f"{base_url}/rest/servicedeskapi/servicedesk"
    # First call returns 429 with Retry-After 1s, second returns 200
    responses.add(responses.GET, endpoint, status=429, headers={"Retry-After": "1"})
    responses.add(responses.GET, endpoint, json={"values": [{"id": "1", "projectKey": "IT"}]}, status=200)

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    desks = client.get_service_desks()
    assert len(desks) == 1
    assert desks[0]["projectKey"] == "IT"
    assert len(responses.calls) == 2
    mock_sleep.assert_called_once_with(1)

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
            "values": [{"id": "1", "body": "Comment 1", "author": {"displayName": "User 1"}}],
        },
        status=200,
    )
    # Page 2: returns 1 comment, isLastPage=True
    responses.add(
        responses.GET,
        endpoint,
        json={
            "isLastPage": True,
            "values": [{"id": "2", "body": "Comment 2", "author": {"displayName": "User 2"}}],
        },
        status=200,
    )

    client = JsmClient(base_url=base_url, user_email="a@b.com", api_token="tok")
    all_comments = client.get_request_comments("IT-200")
    assert len(all_comments) == 2
    assert all_comments[0]["body"] == "Comment 1"
    assert all_comments[1]["body"] == "Comment 2"
    assert len(responses.calls) == 2
