from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.onyxbot.slack.icons import source_to_github_img_link


def _sample_request(
    issue_key: str = "SD-101",
    epoch_ms: int = 1730000000000,
) -> dict[str, Any]:
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
        "sla": {
            "values": [
                {
                    "id": "1",
                    "name": "Time to first response",
                    "ongoingCycle": {
                        "startTime": {"epochMillis": epoch_ms - 60_000},
                        "breachTime": {"epochMillis": epoch_ms + 300_000},
                        "breached": False,
                    },
                    "completedCycles": {
                        "values": [
                            {
                                "startTime": {"epochMillis": epoch_ms - 120_000},
                                "stopTime": {"epochMillis": epoch_ms - 60_000},
                                "breachTime": {"epochMillis": epoch_ms},
                                "breached": False,
                            }
                        ]
                    },
                }
            ]
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


def test_jsm_source_icon_mapping() -> None:
    for source in DocumentSource:
        link = source_to_github_img_link(source)
        assert link.startswith("https://")


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
        "https://acme.atlassian.net/rest/servicedeskapi/servicedesk",
        auth=("bot@example.com", "tok"),
        params={"start": 0, "limit": 1},
    )


def test_jsm_validate_rejects_invalid_scheme() -> None:
    connector = JiraServiceManagementConnector(jsm_base_url="http://acme.atlassian.net")
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "tok"}
    )
    with pytest.raises(ConnectorValidationError, match="https://"):
        connector.validate_connector_settings()


def test_jsm_validate_rejects_request_type_without_service_desk() -> None:
    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net",
        request_type_id="12",
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "tok"}
    )
    with pytest.raises(ConnectorValidationError, match="service_desk_id"):
        connector.validate_connector_settings()


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_load_from_state_filters_internal_comments_and_indexes_sla(
    mock_get: MagicMock,
) -> None:
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
                "body": "Missing public flag note",
                "author": {"displayName": "Agent"},
            },
            {
                "body": "Reset VPN profile and retry.",
                "public": True,
                "created": {"epochMillis": 1730000010000},
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

    mock_get.assert_any_call(
        "https://acme.atlassian.net/rest/servicedeskapi/request",
        auth=("bot@example.com", "secret"),
        params={
            "expand": "sla,comment",
            "requestOwnership": "ALL_REQUESTS",
            "serviceDeskId": "1",
            "start": 0,
            "limit": 50,
        },
    )

    doc = batches[0][0]
    assert isinstance(doc, Document)
    assert doc.id == "jsm:https://acme.atlassian.net:SD-101"
    assert doc.semantic_identifier == "SD-101: VPN gateway timeout"
    assert doc.metadata["service_desk_id"] == "1"
    assert doc.metadata["request_type_id"] == "12"
    assert "sla" in doc.metadata
    text = doc.sections[0].text or ""
    assert "Cannot connect to EU-Central VPN." in text
    assert "Priority: High" in text
    assert "Time to first response (ongoing)" in text
    assert "Time to first response (completed)" in text
    assert "Support Engineer: Reset VPN profile and retry." in text
    assert "Internal triage note" not in text
    assert "Missing public flag note" not in text


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_embedded_comments_avoids_extra_http_call_and_fetches_remaining_pages(
    mock_get: MagicMock,
) -> None:
    req_complete = _sample_request(issue_key="SD-101", epoch_ms=1730000000000)
    req_complete["comments"] = {
        "start": 0,
        "limit": 50,
        "size": 2,
        "isLastPage": True,
        "values": [
            {
                "body": "Internal embedded note",
                "public": False,
                "author": {"displayName": "Agent"},
            },
            {
                "body": "Embedded public answer",
                "public": True,
                "created": {"epochMillis": 1730000010000},
                "author": {"displayName": "Support Engineer"},
            },
        ],
    }

    req_paged = _sample_request(issue_key="SD-102", epoch_ms=1730000000000)
    req_paged["comments"] = {
        "start": 0,
        "limit": 1,
        "size": 1,
        "isLastPage": False,
        "values": [
            {
                "body": "First page comment",
                "public": True,
                "created": {"epochMillis": 1730000005000},
                "author": {"displayName": "Alice"},
            }
        ],
    }

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [req_complete, req_paged],
        "isLastPage": True,
    }
    page2_comment_resp = MagicMock()
    page2_comment_resp.json.return_value = {
        "values": [
            {
                "body": "Second page comment",
                "public": True,
                "created": {"epochMillis": 1730000020000},
                "author": {"displayName": "Bob"},
            }
        ],
        "isLastPage": True,
    }
    mock_get.side_effect = [req_resp, page2_comment_resp]

    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "secret"}
    )

    batches = list(connector.load_from_state())
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert mock_get.call_count == 2
    mock_get.assert_any_call(
        "https://acme.atlassian.net/rest/servicedeskapi/request/SD-102/comment",
        auth=("bot@example.com", "secret"),
        params={"start": 1, "limit": 50},
    )

    doc1, doc2 = batches[0]
    text1 = doc1.sections[0].text or ""
    assert "Support Engineer: Embedded public answer" in text1
    assert "Internal embedded note" not in text1

    text2 = doc2.sections[0].text or ""
    assert "Alice: First page comment" in text2
    assert "Bob: Second page comment" in text2
    assert doc2.doc_updated_at is not None
    assert doc2.doc_updated_at.timestamp() == 1730000020.0


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_poll_source_includes_new_public_comment_activity(
    mock_get: MagicMock,
) -> None:
    status_updated_in_window = _sample_request(
        issue_key="SD-101", epoch_ms=1730000000000
    )
    old_status_with_new_comment = _sample_request(
        issue_key="SD-100", epoch_ms=1720000000000
    )
    old_status_no_new_activity = _sample_request(
        issue_key="SD-099", epoch_ms=1710000000000
    )

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [
            status_updated_in_window,
            old_status_with_new_comment,
            old_status_no_new_activity,
        ],
        "isLastPage": True,
    }
    comment_resp_101 = MagicMock()
    comment_resp_101.json.return_value = {"values": [], "isLastPage": True}

    comment_resp_100 = MagicMock()
    comment_resp_100.json.return_value = {
        "values": [
            {
                "body": "Follow-up from customer",
                "public": True,
                "created": {"epochMillis": 1731000000000},
                "author": {"displayName": "Customer"},
            }
        ],
        "isLastPage": True,
    }

    comment_resp_099 = MagicMock()
    comment_resp_099.json.return_value = {"values": [], "isLastPage": True}

    mock_get.side_effect = [
        req_resp,
        comment_resp_101,
        comment_resp_100,
        comment_resp_099,
    ]

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
        "jsm:https://acme.atlassian.net:SD-101",
        "jsm:https://acme.atlassian.net:SD-100",
    ]


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_comment_fetch_failure_propagates(mock_get: MagicMock) -> None:
    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [_sample_request()],
        "isLastPage": True,
    }
    mock_get.side_effect = [req_resp, requests.HTTPError("502 Bad Gateway")]

    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "secret"}
    )

    with pytest.raises(requests.HTTPError):
        list(connector.load_from_state())


@patch("onyx.connectors.jira_service_management.connector._jsm_get")
def test_jsm_sla_breach_time_recorded_only_when_breached(
    mock_get: MagicMock,
) -> None:
    unbreached_req = _sample_request(issue_key="SD-101", epoch_ms=1730000000000)
    unbreached_req["comments"] = {"isLastPage": True, "values": []}

    breached_req = _sample_request(issue_key="SD-102", epoch_ms=1730000000000)
    breached_req["sla"]["values"][0]["ongoingCycle"]["breachTime"] = {
        "epochMillis": 1730000040000
    }
    breached_req["sla"]["values"][0]["ongoingCycle"]["breached"] = True
    breached_req["comments"] = {"isLastPage": True, "values": []}

    req_resp = MagicMock()
    req_resp.json.return_value = {
        "values": [unbreached_req, breached_req],
        "isLastPage": True,
    }
    mock_get.side_effect = [req_resp]

    connector = JiraServiceManagementConnector(
        jsm_base_url="https://acme.atlassian.net"
    )
    connector.load_credentials(
        {"jira_user_email": "bot@example.com", "jira_api_token": "secret"}
    )

    batches = list(
        connector.poll_source(start=1729999900.0, end=1730000050.0)
    )
    assert len(batches) == 1
    assert len(batches[0]) == 2
    doc_unbreached, doc_breached = batches[0]
    assert doc_unbreached.id == "jsm:https://acme.atlassian.net:SD-101"
    assert doc_unbreached.doc_updated_at is not None
    assert doc_unbreached.doc_updated_at.timestamp() == 1730000000.0

    assert doc_breached.id == "jsm:https://acme.atlassian.net:SD-102"
    assert doc_breached.doc_updated_at is not None
    assert doc_breached.doc_updated_at.timestamp() == 1730000040.0
