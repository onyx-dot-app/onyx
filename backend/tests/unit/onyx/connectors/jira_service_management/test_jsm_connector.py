from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from client import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    JiraServiceManagementClient,
    parse_jira_datetime,
)
from connector import (
    Document,
    DocumentSource,
    JiraServiceManagementConnector,
    SlimDocument,
)


@pytest.fixture
def mock_service_desks_response():
    return {
        "isLastPage": True,
        "values": [
            {
                "id": "1",
                "projectId": "10001",
                "projectName": "IT Service Desk",
                "projectKey": "IT",
            },
            {
                "id": "2",
                "projectId": "10002",
                "projectName": "Customer Support",
                "projectKey": "CS",
            },
        ],
    }


@pytest.fixture
def mock_request_page_response():
    return {
        "isLastPage": True,
        "values": [
            {
                "issueId": "2001",
                "issueKey": "IT-101",
                "serviceDeskId": "1",
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "VPN Connection Issue"},
                    {
                        "fieldId": "description",
                        "value": "Cannot connect to the VPN gateway.",
                    },
                ],
                "currentStatus": {"status": "Waiting for support"},
                "requestType": {"id": "10", "name": "IT Help"},
                "reporter": {
                    "displayName": "Alice Smith",
                    "emailAddress": "alice@example.com",
                },
                "assignee": {
                    "displayName": "Bob Tech",
                    "emailAddress": "bob@example.com",
                },
                "createdDate": {"iso8601": "2026-03-01T10:00:00.000+0000"},
                "updatedDate": {"iso8601": "2026-03-02T15:30:00.000+0000"},
            }
        ],
    }


@pytest.fixture
def mock_comments_response():
    return {
        "values": [
            {
                "id": "301",
                "body": "Looking into the logs now.",
                "public": True,
                "author": {"displayName": "Bob Tech", "emailAddress": "bob@example.com"},
                "created": {"iso8601": "2026-03-02T11:00:00.000+0000"},
            },
            {
                "id": "302",
                "body": "Internal note: check LDAP server sync.",
                "public": False,
                "author": {"displayName": "Bob Tech", "emailAddress": "bob@example.com"},
                "created": {"iso8601": "2026-03-02T12:00:00.000+0000"},
            },
        ]
    }


def test_parse_jira_datetime():
    dt = parse_jira_datetime("2026-03-01T10:00:00.000+0000")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3
    assert dt.day == 1
    assert dt.hour == 10
    assert dt.tzinfo == timezone.utc

    dt_z = parse_jira_datetime("2026-03-01T10:00:00Z")
    assert dt_z is not None
    assert dt_z.tzinfo == timezone.utc

    assert parse_jira_datetime("invalid") is None
    assert parse_jira_datetime(None) is None


def test_client_auth_headers():
    client_basic = JiraServiceManagementClient(
        base_url="https://company.atlassian.net",
        user_email="admin@company.com",
        api_token="secret_token",
    )
    assert "Basic " in client_basic.session.headers["Authorization"]

    client_pat = JiraServiceManagementClient(
        base_url="https://company.atlassian.net",
        pat_token="pat_token_123",
    )
    assert client_pat.session.headers["Authorization"] == "Bearer pat_token_123"

    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementClient(base_url="https://company.atlassian.net")


def test_client_get_service_desks(mock_service_desks_response):
    client = JiraServiceManagementClient(
        base_url="https://company.atlassian.net",
        pat_token="token",
    )

    with patch.object(client.session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_service_desks_response
        mock_get.return_value = mock_resp

        desks = client.get_service_desks()
        assert len(desks) == 2
        assert desks[0].project_key == "IT"
        assert desks[0].project_name == "IT Service Desk"
        assert desks[1].project_key == "CS"

        found_it = client.get_service_desk_by_key("IT")
        assert found_it is not None
        assert found_it.id == "1"

        not_found = client.get_service_desk_by_key("UNKNOWN")
        assert not_found is None


def test_client_error_handling():
    client = JiraServiceManagementClient(
        base_url="https://company.atlassian.net",
        pat_token="token",
    )

    with patch.object(client.session, "get") as mock_get:
        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_get.return_value = mock_401
        with pytest.raises(CredentialExpiredError):
            client.test_connection()

        mock_403 = MagicMock()
        mock_403.status_code = 403
        mock_get.return_value = mock_403
        with pytest.raises(InsufficientPermissionsError):
            client.get_service_desks()


def test_connector_load_from_state(
    mock_service_desks_response,
    mock_request_page_response,
    mock_comments_response,
):
    connector = JiraServiceManagementConnector(
        project_key="IT",
        include_internal_comments=True,
        batch_size=10,
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://company.atlassian.net",
            "pat_token": "token_abc",
        }
    )

    with patch.object(connector.client.session, "get") as mock_get:
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "servicedeskapi/servicedesk" in url and "request" not in url:
                resp.json.return_value = mock_service_desks_response
            elif "comment" in url:
                resp.json.return_value = mock_comments_response
            else:
                resp.json.return_value = mock_request_page_response
            return resp

        mock_get.side_effect = side_effect

        batches = list(connector.load_from_state())
        assert len(batches) == 1
        docs = batches[0]
        assert len(docs) == 1

        doc = docs[0]
        assert isinstance(doc, Document)
        assert doc.id == "https://company.atlassian.net/browse/IT-101"
        assert doc.source == DocumentSource.JIRA
        assert doc.semantic_identifier == "IT-101: VPN Connection Issue"
        assert doc.metadata["project"] == "IT"
        assert doc.metadata["status"] == "Waiting for support"
        assert doc.metadata["request_type"] == "IT Help"
        assert doc.metadata["reporter"] == "alice@example.com"
        assert doc.metadata["assignee"] == "bob@example.com"

        full_text = doc.sections[0].text
        assert "VPN Connection Issue" in full_text
        assert "Cannot connect to the VPN gateway." in full_text
        assert "Looking into the logs now." in full_text
        assert "Internal note: check LDAP server sync." in full_text


def test_connector_poll_source(
    mock_service_desks_response,
    mock_request_page_response,
    mock_comments_response,
):
    connector = JiraServiceManagementConnector(
        service_desk_id="1",
        batch_size=10,
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://company.atlassian.net",
            "pat_token": "token_abc",
        }
    )

    with patch.object(connector.client.session, "get") as mock_get:
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "comment" in url:
                resp.json.return_value = mock_comments_response
            else:
                resp.json.return_value = mock_request_page_response
            return resp

        mock_get.side_effect = side_effect

        start_ts = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc).timestamp()
        end_ts = datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc).timestamp()

        batches = list(connector.poll_source(start=start_ts, end=end_ts))
        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].id == "https://company.atlassian.net/browse/IT-101"

        old_start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        old_end = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

        empty_batches = list(connector.poll_source(start=old_start, end=old_end))
        assert len(empty_batches) == 0


def test_connector_retrieve_all_slim_docs(
    mock_service_desks_response,
    mock_request_page_response,
):
    connector = JiraServiceManagementConnector(
        service_desk_id="1",
        batch_size=10,
    )
    connector.load_credentials(
        {
            "jira_base_url": "https://company.atlassian.net",
            "pat_token": "token_abc",
        }
    )

    with patch.object(connector.client.session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_request_page_response
        mock_get.return_value = mock_resp

        batches = list(connector.retrieve_all_slim_docs())
        assert len(batches) == 1
        slim_docs = batches[0]
        assert len(slim_docs) == 1

        slim_doc = slim_docs[0]
        assert isinstance(slim_doc, SlimDocument)
        assert slim_doc.id == "https://company.atlassian.net/browse/IT-101"
        assert slim_doc.doc_created_at == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
