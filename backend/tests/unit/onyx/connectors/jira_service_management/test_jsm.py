"""Unit tests for the Jira Service Management connector."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jsm_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementApiClient,
    JiraServiceManagementConnector,
    _build_jsm_jql,
    _extract_request_type,
    _issue_to_document,
    _request_to_document,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


def test_jsm_config_validation() -> None:
    config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
        service_desk_id="1",
        batch_size=25,
    )
    assert config.jira_base_url == "https://example.atlassian.net"
    assert config.project_key == "ITSM"
    assert config.service_desk_id == "1"
    assert config.batch_size == 25


def test_jsm_config_order_by_rejected() -> None:
    with pytest.raises(ValueError):
        JiraServiceManagementConnectorConfig(
            jira_base_url="https://example.atlassian.net",
            jql_query="project = ITSM ORDER BY created DESC",
        )


def test_jsm_planning_rule() -> None:
    old = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net",
        jql_query="project = ITSM",
        project_key="ITSM",
    )
    new = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net",
        jql_query="project = HR",
        project_key="HR",
    )
    rule = jsm_planning_rule(old, new)
    assert rule is not None
    assert "project_key" in rule.scope_directions


def test_build_jsm_jql() -> None:
    # Empty clauses fallback to valid search restriction
    assert _build_jsm_jql() == "project is not EMPTY ORDER BY updated ASC"

    # Project key only
    jql = _build_jsm_jql(project_key="ITSM")
    assert jql == 'project = "ITSM" ORDER BY updated ASC'

    # Custom JQL
    jql = _build_jsm_jql(custom_jql="issuetype = 'Service Request'")
    assert jql == "(issuetype = 'Service Request') ORDER BY updated ASC"

    # With time filter
    start = 1700000000
    end = 1700086400
    jql = _build_jsm_jql(project_key="ITSM", start=start, end=end)
    assert 'project = "ITSM"' in jql
    assert 'updated >= "' in jql
    assert 'updated <= "' in jql
    assert jql.endswith("ORDER BY updated ASC")


def test_extract_request_type() -> None:
    # Dict request type
    issue_dict = {
        "fields": {
            "customfield_10010": {
                "requestType": {"name": "Laptop Replacement"}
            }
        }
    }
    assert _extract_request_type(issue_dict) == "Laptop Replacement"

    # String request type
    issue_str = {"fields": {"customfield_10010": "VPN Access"}}
    assert _extract_request_type(issue_str) == "VPN Access"

    # Fallback to issuetype
    issue_fallback = {"fields": {"issuetype": {"name": "Incident"}}}
    assert _extract_request_type(issue_fallback) == "Incident"


def test_issue_to_document_conversion() -> None:
    issue = {
        "key": "ITSM-101",
        "fields": {
            "summary": "Cannot connect to VPN",
            "description": "Getting error 403 when connecting from home.",
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "issuetype": {"name": "IT Help"},
            "project": {"key": "ITSM", "name": "IT Service Management"},
            "reporter": {
                "displayName": "Alice Smith",
                "emailAddress": "alice@example.com",
            },
            "assignee": {
                "displayName": "Bob Tech",
                "emailAddress": "bob@example.com",
            },
            "created": "2026-10-01T10:00:00.000Z",
            "updated": "2026-10-02T15:30:00.000Z",
            "labels": ["vpn", "network"],
            "comment": {
                "comments": [
                    {
                        "author": {
                            "displayName": "Bob Tech",
                            "emailAddress": "bob@example.com",
                        },
                        "body": "Checking VPN certificates now.",
                    },
                    {
                        "author": {
                            "displayName": "Bot",
                            "emailAddress": "bot@blacklisted.com",
                        },
                        "body": "Automated status notification.",
                    },
                ]
            },
        },
    }

    doc = _issue_to_document(
        issue=issue,
        jira_base_url="https://mycompany.atlassian.net",
        comment_email_blacklist=("bot@blacklisted.com",),
        labels_to_skip={"sensitive"},
    )

    assert doc is not None
    assert doc.id == "https://mycompany.atlassian.net/browse/ITSM-101"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "ITSM-101: Cannot connect to VPN"
    assert doc.title == "ITSM-101 Cannot connect to VPN"
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["priority"] == "High"
    assert doc.metadata["project"] == "ITSM"
    assert doc.metadata["reporter_email"] == "alice@example.com"
    assert doc.metadata["assignee_email"] == "bob@example.com"
    assert "vpn" in doc.metadata["labels"]

    # Check comments filtering
    section_text = doc.sections[0].text
    assert "Checking VPN certificates now." in section_text
    assert "Automated status notification." not in section_text


def test_issue_to_document_labels_to_skip() -> None:
    issue = {
        "key": "ITSM-102",
        "fields": {
            "summary": "Confidential security issue",
            "labels": ["confidential", "security"],
        },
    }
    doc = _issue_to_document(
        issue=issue,
        jira_base_url="https://mycompany.atlassian.net",
        labels_to_skip={"confidential"},
    )
    assert doc is None


def test_request_to_document_conversion() -> None:
    req = {
        "issueKey": "SD-42",
        "serviceDeskId": "1",
        "requestTypeId": "5",
        "createdDate": {"iso8601": "2026-10-15T08:00:00.000Z"},
        "currentStatus": {"status": "Waiting for Support"},
        "reporter": {
            "displayName": "Charlie Customer",
            "emailAddress": "charlie@client.com",
        },
        "requestFieldValues": [
            {"fieldId": "summary", "value": "Password reset needed"},
            {"fieldId": "description", "value": "Locked out after 3 attempts"},
            {"fieldId": "priority", "value": {"name": "Urgent"}},
        ],
    }

    comments = [
        {
            "author": {"displayName": "Agent", "emailAddress": "agent@desk.com"},
            "body": "Temporary password sent.",
        }
    ]

    doc = _request_to_document(
        req=req,
        jira_base_url="https://support.example.com",
        comments=comments,
    )

    assert doc is not None
    assert doc.id == "https://support.example.com/browse/SD-42"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "SD-42: Password reset needed"
    assert doc.metadata["status"] == "Waiting for Support"
    assert doc.metadata["priority"] == "Urgent"
    assert doc.metadata["service_desk_id"] == "1"
    assert doc.metadata["reporter_email"] == "charlie@client.com"
    assert "Temporary password sent." in doc.sections[0].text


def test_api_client_auth_cloud() -> None:
    client = JiraServiceManagementApiClient(
        jira_base_url="https://example.atlassian.net/",
        jira_user_email="agent@example.com",
        jira_api_token="secret_token",
    )
    assert client.jira_base_url == "https://example.atlassian.net"
    assert client.auth == ("agent@example.com", "secret_token")
    assert "Authorization" not in client.headers


def test_api_client_auth_pat() -> None:
    client = JiraServiceManagementApiClient(
        jira_base_url="https://jira.datacenter.internal",
        jira_user_email=None,
        jira_api_token="pat_token_123",
    )
    assert client.auth is None
    assert client.headers["Authorization"] == "Bearer pat_token_123"


@patch("onyx.connectors.jira_service_management.connector.rl_requests.get")
def test_api_client_errors(mock_get: MagicMock) -> None:
    client = JiraServiceManagementApiClient(
        jira_base_url="https://example.atlassian.net",
        jira_user_email="a@b.com",
        jira_api_token="tok",
    )

    # 401 Unauthorized -> CredentialExpiredError
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_get.return_value = mock_resp_401
    with pytest.raises(CredentialExpiredError):
        client.get_service_desks()

    # 403 Forbidden -> InsufficientPermissionsError
    mock_resp_403 = MagicMock()
    mock_resp_403.status_code = 403
    mock_get.return_value = mock_resp_403
    with pytest.raises(InsufficientPermissionsError):
        client.get_service_desks()


def test_connector_missing_credential_error() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({"jira_api_token": ""})


@patch.object(JiraServiceManagementApiClient, "search_issues_jql")
def test_connector_load_from_state(mock_search: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
        batch_size=2,
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_user_email": "agent@example.com",
            "jira_api_token": "token123",
        }
    )

    mock_search.return_value = {
        "issues": [
            {
                "key": "ITSM-1",
                "fields": {"summary": "Issue 1", "status": {"name": "Open"}},
            },
            {
                "key": "ITSM-2",
                "fields": {"summary": "Issue 2", "status": {"name": "Closed"}},
            },
        ],
        "total": 2,
    }

    batches = list(connector.load_from_state())
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert batches[0][0].id == "https://example.atlassian.net/browse/ITSM-1"
    assert batches[0][1].id == "https://example.atlassian.net/browse/ITSM-2"


@patch.object(JiraServiceManagementApiClient, "search_issues_jql")
def test_connector_poll_source(mock_search: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_user_email": "agent@example.com",
            "jira_api_token": "token123",
        }
    )

    mock_search.return_value = {
        "issues": [
            {
                "key": "ITSM-10",
                "fields": {"summary": "Recent incident"},
            }
        ],
        "total": 1,
    }

    batches = list(connector.poll_source(start=1700000000, end=1700086400))
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert batches[0][0].title == "ITSM-10 Recent incident"

    # Verify JQL contained the time filters
    called_jql = mock_search.call_args.kwargs["jql"]
    assert 'updated >= "' in called_jql
    assert 'updated <= "' in called_jql


@patch.object(JiraServiceManagementApiClient, "search_issues_jql")
def test_connector_retrieve_all_slim_docs(mock_search: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
        batch_size=2,
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "token123",
        }
    )

    mock_search.return_value = {
        "issues": [
            {"key": "ITSM-1", "fields": {"labels": []}},
            {"key": "ITSM-2", "fields": {"labels": ["skip_me"]}},
            {"key": "ITSM-3", "fields": {"labels": []}},
        ],
        "total": 3,
    }
    connector.labels_to_skip = {"skip_me"}

    mock_callback = MagicMock(spec=IndexingHeartbeatInterface)
    mock_callback.should_stop.return_value = False
    batches = list(connector.retrieve_all_slim_docs(callback=mock_callback))

    assert mock_callback.progress.called
    flat_docs = [doc for batch in batches for doc in batch]
    assert len(flat_docs) == 2
    assert flat_docs[0].id == "https://example.atlassian.net/browse/ITSM-1"
    assert flat_docs[1].id == "https://example.atlassian.net/browse/ITSM-3"


@patch.object(JiraServiceManagementApiClient, "get_customer_requests")
@patch.object(JiraServiceManagementApiClient, "get_request_comments")
def test_connector_service_desk_api_mode(
    mock_comments: MagicMock,
    mock_requests: MagicMock,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id="5",
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "tok",
        }
    )

    mock_requests.return_value = {
        "values": [
            {
                "issueKey": "IT-99",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Service Desk ticket"}
                ],
                "currentStatus": {"status": "Waiting for agent"},
            }
        ],
        "isLastPage": True,
    }
    mock_comments.return_value = []

    batches = list(connector.load_from_state())
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert batches[0][0].id == "https://example.atlassian.net/browse/IT-99"
    assert batches[0][0].title == "IT-99 Service Desk ticket"


@patch.object(JiraServiceManagementApiClient, "get_customer_requests")
@patch.object(JiraServiceManagementApiClient, "get_request_comments")
def test_connector_service_desk_labels_and_time_filter(
    mock_comments: MagicMock,
    mock_requests: MagicMock,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id="5",
        labels_to_skip=["skip_me"],
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "tok",
        }
    )

    mock_requests.return_value = {
        "values": [
            {
                "issueKey": "IT-1",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Normal ticket"},
                    {"fieldId": "updated", "value": "2026-10-10T12:00:00.000Z"},
                ],
            },
            {
                "issueKey": "IT-2",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Skipped label"},
                    {"fieldId": "labels", "value": ["skip_me"]},
                    {"fieldId": "updated", "value": "2026-10-10T12:00:00.000Z"},
                ],
            },
            {
                "issueKey": "IT-3",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Old ticket"},
                    {"fieldId": "updated", "value": "2026-09-01T12:00:00.000Z"},
                ],
            },
        ],
        "isLastPage": True,
    }
    mock_comments.return_value = []

    # Polling from 2026-10-01
    start = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp())
    batches = list(connector.poll_source(start=start, end=end))
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert batches[0][0].id == "https://example.atlassian.net/browse/IT-1"


@patch.object(JiraServiceManagementApiClient, "get_customer_requests")
def test_connector_service_desk_retrieve_all_slim_docs(mock_requests: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id="5",
        labels_to_skip=["skip_me"],
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "tok",
        }
    )

    mock_requests.return_value = {
        "values": [
            {
                "issueKey": "IT-1",
                "requestFieldValues": [
                    {"fieldId": "labels", "value": []},
                    {"fieldId": "updated", "value": "2026-10-10T12:00:00.000Z"},
                ],
            },
            {
                "issueKey": "IT-2",
                "requestFieldValues": [
                    {"fieldId": "labels", "value": ["skip_me"]},
                    {"fieldId": "updated", "value": "2026-10-10T12:00:00.000Z"},
                ],
            },
        ],
        "isLastPage": True,
    }

    mock_callback = MagicMock(spec=IndexingHeartbeatInterface)
    mock_callback.should_stop.return_value = False
    batches = list(connector.retrieve_all_slim_docs(callback=mock_callback))

    assert mock_callback.progress.called
    flat_docs = [doc for batch in batches for doc in batch]
    assert len(flat_docs) == 1
    assert flat_docs[0].id == "https://example.atlassian.net/browse/IT-1"


@patch("onyx.connectors.jira_service_management.connector.scoped_url")
def test_api_client_scoped_token(mock_scoped_url: MagicMock) -> None:
    mock_scoped_url.return_value = "https://api.atlassian.com/ex/jira/12345"
    client = JiraServiceManagementApiClient(
        jira_base_url="https://example.atlassian.net",
        jira_user_email="agent@example.com",
        jira_api_token="token",
        scoped_token=True,
    )
    assert client.jira_base_url == "https://api.atlassian.com/ex/jira/12345"
    assert client.raw_base_url == "https://example.atlassian.net"
    mock_scoped_url.assert_called_once_with("https://example.atlassian.net", "jira")


@patch.object(JiraServiceManagementApiClient, "_request")
def test_get_request_comments_propagates_exception(mock_request: MagicMock) -> None:
    client = JiraServiceManagementApiClient(
        jira_base_url="https://example.atlassian.net",
        jira_user_email="agent@example.com",
        jira_api_token="token",
    )
    mock_request.side_effect = requests.exceptions.HTTPError("500 Internal Server Error")
    with pytest.raises(requests.exceptions.HTTPError):
        client.get_request_comments("SD-100")


@patch.object(JiraServiceManagementApiClient, "get_customer_requests")
@patch.object(JiraServiceManagementApiClient, "get_request_comments")
def test_service_desk_comment_timestamp_updates_doc(
    mock_comments: MagicMock,
    mock_requests: MagicMock,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id="10",
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "tok",
        }
    )

    # Request has older timestamp: 2026-10-01
    mock_requests.return_value = {
        "values": [
            {
                "issueKey": "SD-101",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Old ticket with new comment"},
                    {"fieldId": "updated", "value": "2026-10-01T10:00:00.000Z"},
                ],
                "createdDate": {"iso8601": "2026-10-01T09:00:00.000Z"},
            }
        ],
        "isLastPage": True,
    }
    # Comment added on 2026-10-20
    mock_comments.return_value = [
        {
            "author": {"displayName": "Helper", "emailAddress": "helper@example.com"},
            "body": "Fixed this today!",
            "created": {"iso8601": "2026-10-20T15:30:00.000Z"},
        }
    ]

    # Poll window: 2026-10-15 to 2026-10-22
    start_ts = int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())

    batches = list(connector.poll_source(start=start_ts, end=end_ts))
    assert len(batches) == 1
    assert len(batches[0]) == 1
    doc = batches[0][0]
    assert doc.id == "https://example.atlassian.net/browse/SD-101"
    assert doc.doc_updated_at == datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
    assert "Fixed this today!" in doc.sections[0].text


@patch.object(JiraServiceManagementApiClient, "get_customer_requests")
@patch.object(JiraServiceManagementApiClient, "get_request_comments")
def test_retrieve_all_slim_docs_propagates_comment_fetch_error(
    mock_comments: MagicMock,
    mock_requests: MagicMock,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id="10",
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://example.atlassian.net",
            "jira_api_token": "tok",
        }
    )

    mock_requests.return_value = {
        "values": [
            {
                "issueKey": "SD-102",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "Failing comment ticket"},
                    {"fieldId": "updated", "value": "2026-10-01T10:00:00.000Z"},
                ],
            }
        ],
        "isLastPage": True,
    }
    mock_comments.side_effect = requests.exceptions.HTTPError("502 Bad Gateway")

    with pytest.raises(requests.exceptions.HTTPError):
        list(connector.retrieve_all_slim_docs(start=1700000000, end=1700086400))

@patch.object(JiraServiceManagementApiClient, "_request")
def test_get_request_comments_paginates_all_pages(mock_request: MagicMock) -> None:
    """Verify get_request_comments follows start/limit/isLastPage until all comment pages are fetched."""
    client = JiraServiceManagementApiClient(
        jira_base_url="https://example.atlassian.net",
        jira_user_email="agent@example.com",
        jira_api_token="token",
    )
    mock_request.side_effect = [
        {
            "values": [{"id": "c1", "body": "First page comment"}],
            "isLastPage": False,
        },
        {
            "values": [{"id": "c2", "body": "Second page comment"}],
            "isLastPage": True,
        },
    ]
    comments = client.get_request_comments("SD-200")
    assert len(comments) == 2
    assert [c["id"] for c in comments] == ["c1", "c2"]
    assert mock_request.call_count == 2
