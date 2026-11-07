from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError


def _make_mock_response(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _sample_service_desk_payload() -> dict[str, Any]:
    return {
        "values": [
            {"id": "10", "projectKey": "ITSM", "projectName": "IT Service Desk"},
            {"id": "20", "projectKey": "HR", "projectName": "HR Desk"},
        ],
        "isLastPage": True,
    }


def _sample_requests_payload() -> dict[str, Any]:
    return {
        "values": [
            {
                "issueId": "10001",
                "issueKey": "ITSM-1",
                "serviceDeskId": "10",
                "requestTypeId": "25",
                "createdDate": {"epochMillis": 1700000000000},
                "currentStatus": {
                    "status": "Waiting for support",
                    "statusDate": {"epochMillis": 1700003600000},
                },
                "reporter": {
                    "displayName": "Alice Smith",
                    "emailAddress": "alice@example.com",
                },
                "requestFieldValues": [
                    {"fieldId": "summary", "value": "VPN access issue"},
                    {
                        "fieldId": "description",
                        "value": "Cannot connect to corporate VPN from macOS.",
                    },
                ],
                "_links": {"web": "https://example.atlassian.net/browse/ITSM-1"},
            }
        ],
        "isLastPage": True,
    }


def _sample_comments_payload() -> dict[str, Any]:
    return {
        "values": [
            {"id": "900", "body": "Reset MFA profile and re-issued certificate."}
        ],
        "isLastPage": True,
    }


def test_config_normalizes_project_key() -> None:
    cfg = JiraServiceManagementConnectorConfig(
        base_url="https://example.atlassian.net",
        project_key="  itsm ",
    )
    assert cfg.project_key == "ITSM"
    empty_cfg = JiraServiceManagementConnectorConfig(
        base_url="https://example.atlassian.net",
        project_key="   ",
    )
    assert empty_cfg.project_key is None


def test_missing_credentials_raises() -> None:
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({"jira_user_email": "alice@example.com"})
    with pytest.raises(ConnectorMissingCredentialError):
        list(connector.load_from_state())


@patch("onyx.connectors.jira_service_management.connector.rl_requests.get")
def test_load_from_state_and_slim_documents(mock_get: MagicMock) -> None:
    def side_effect(url: str, **kwargs: Any) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _make_mock_response(_sample_service_desk_payload())
        if url.endswith("/rest/servicedeskapi/request"):
            return _make_mock_response(_sample_requests_payload())
        if "/comment" in url:
            return _make_mock_response(_sample_comments_payload())
        raise AssertionError(f"Unexpected URL: {url}")

    mock_get.side_effect = side_effect

    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="itsm",
    )
    connector.load_credentials(
        {
            "jira_user_email": "bot@example.com",
            "jira_api_token": "secret-token",
        }
    )

    batches = list(connector.load_from_state())
    assert len(batches) == 1
    doc = batches[0][0]
    assert doc.id == "JSM_ITSM-1"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "ITSM-1: VPN access issue"
    assert doc.metadata["project_key"] == "ITSM"
    assert doc.metadata["status"] == "Waiting for support"
    assert len(doc.sections) == 2

    slim_batches = list(connector.retrieve_all_slim_documents())
    assert len(slim_batches) == 1
    assert slim_batches[0][0].id == "JSM_ITSM-1"


@patch("onyx.connectors.jira_service_management.connector.rl_requests.get")
def test_poll_source_filters_by_timestamp_window(mock_get: MagicMock) -> None:
    mock_get.side_effect = [
        _make_mock_response(_sample_service_desk_payload()),
        _make_mock_response(_sample_requests_payload()),
        _make_mock_response(_sample_comments_payload()),
        _make_mock_response(_sample_service_desk_payload()),
        _make_mock_response(_sample_requests_payload()),
    ]

    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    connector.load_credentials(
        {"user_email": "bot@example.com", "api_token": "secret-token"}
    )

    in_window = list(connector.poll_source(1700000000.0, 1700005000.0))
    assert len(in_window) == 1

    out_of_window = list(connector.poll_source(1700010000.0, 1700020000.0))
    assert len(out_of_window) == 0
