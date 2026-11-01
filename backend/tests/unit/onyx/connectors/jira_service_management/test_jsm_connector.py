from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document


def _sample_request(
    issue_key: str = "SD-101",
    epoch_ms: int = 1730000000000,
) -> dict:
    return {
        "issueId": "10101",
        "issueKey": issue_key,
        "serviceDeskId": "1",
        "requestTypeId": "12",
        "createdDate": {"epochMillis": epoch_ms - 60_000},
        "currentStatus": {
            "status": "Waiting for support",
            "statusDate": {"epochMillis": epoch_ms},
        },
        "reporter": {
            "displayName": "Alice Smith",
            "emailAddress": "alice@example.com",
        },
        "requestFieldValues": [
            {
                "fieldId": "summary",
                "label": "Summary",
                "value": "VPN gateway timeout",
            },
            {
                "fieldId": "description",
                "label": "Description",
                "value": "Cannot connect to EU-Central VPN.",
            },
            {
                "fieldId": "priority",
                "label": "Priority",
                "value": {"name": "High"},
            },
        ],
        "_links": {"web": f"https://acme.atlassian.net/servicedesk/customer/portal/1/{issue_key}"},
    }


def test_jsm_config_matches_connector_init() -> None:
    cfg = JiraServiceManagementConnectorConfig(
        jsm_base_url="https://acme.atlassian.net",
        service_desk_id="1",
        request_type_id="12",
        batch_size=25,
    )
    connector = JiraServiceManagementConnector(**cfg.model_dump())
    assert connector.jsm_base_url == "https://acme.atlassian.net"
    assert connector.service_desk_id == "1"
    assert connector.request_type_id == "12"
    assert connector.batch_size == 25


def test_jsm_missing_credentials_raises() -> None:
    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_validate_connector_settings(mock_get: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "tok"}
    )
    connector.validate_connector_settings()
    mock_get.assert_called_once_with(
        "https://acme.atlassian.net/rest/servicedeskapi/info",
        auth=("bot@example.com", "tok"),
    )


def test_jsm_validate_rejects_invalid_scheme() -> None:
    connector = JiraServiceManagementConnector(jsm_base_url="acme.atlassian.net")
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "tok"}
    )
    with pytest.raises(ConnectorValidationError, match="http"):
        connector.validate_connector_settings()


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_load_from_state_filters_internal_comments(mock_get: MagicMock) -> None:
    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [_sample_request()],
        "isLastPage": True,
    }
    comment_resp = MagicMock()
    comment_resp.json.return_value = {
        "values": [
            {
                "body": "Internal triage note",
                "public": False,
                "author": {"displayName": "Agent"},
            },
            {
                "body": "Reset VPN profile and retry.",
                "public": True,
                "author": {"displayName": "Support Engineer"},
            },
        ],
        "isLastPage": True,
    }
    mock_get.side_effect = [req_resp, comment_resp]

    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net/",
        service_desk_id="1",
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "secret"}
    )

    batches = list(connector.load_from_state())
    assert len(batches) == 1
    assert len(batches[0]) == 1

    doc = batches[0][0]
    assert isinstance(doc, Document)
    assert doc.id == "jsm:https://acme.atlassian.net:SD-101"
    assert doc.semantic_identifier == "SD-101: VPN gateway timeout"
    assert doc.metadata["service_desk_id"] == "1"
    assert doc.metadata["request_type_id"] == "12"
    text = doc.sections[0].text or ""
    assert "Cannot connect to EU-Central VPN." in text
    assert "Priority: High" in text
    assert "Support Engineer: Reset VPN profile and retry." in text
    assert "Internal triage note" not in text


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_poll_source_respects_time_window(mock_get: MagicMock) -> None:
    in_window = _sample_request(issue_key="SD-101", epoch_ms=1730000000000)
    out_of_window = _sample_request(issue_key="SD-100", epoch_ms=1720000000000)

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [in_window, out_of_window],
        "isLastPage": True,
    }
    comment_resp = MagicMock()
    comment_resp.json.return_value = {"values": [], "isLastPage": True}
    mock_get.side_effect = [req_resp, comment_resp]

    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "secret"}
    )

    batches = list(
        connector.poll_source(start=1725000000.0, end=1735000000.0)
    )
    assert len(batches) == 1
    assert [d.id for d in batches[0]] == [
        "jsm:https://acme.atlassian.net:SD-101"
    ]
