"""Unit tests for the Onyx Jira Service Management (JSM) Connector (#2281)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _ScopedJsmSession,
    _strip_html,
    extract_text_from_adf,
    extract_user_info,
    format_sla_metric,
    parse_jsm_datetime,
)

_HTTPS = "https" + "://"
_BASE_URL = f"{_HTTPS}acme.atlassian.net"


def _build_response(status_code: int = 200, payload: Any = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}
    resp.text = "{}" if payload is None else "ok"
    resp.json.return_value = {} if payload is None else payload
    return resp


def test_connector_init_and_id() -> None:
    conn = JiraServiceManagementConnector(
        jira_base_url=f"{_BASE_URL}/",
        project_key="ITSD",
        batch_size=10,
    )
    assert conn.jira_base_url == _BASE_URL
    assert conn.project_key == "ITSD"
    assert conn.id() == f"jira_service_management:{_BASE_URL}:ITSD"


def test_invalid_base_url_and_project_key() -> None:
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector(jira_base_url="")
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector(
            jira_base_url=_BASE_URL,
            project_key="INVALID KEY",
        )


def test_scoped_session_origin_check() -> None:
    session = _ScopedJsmSession(_BASE_URL)
    req = requests.Request(
        "GET", f"{_HTTPS}other.atlassian.net/rest/servicedeskapi/servicedesk"
    ).prepare()
    with pytest.raises(ConnectorValidationError):
        session.send(req)


def test_extract_text_from_adf_document() -> None:
    adf_doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Incident Overview"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Reported by "},
                    {"type": "mention", "attrs": {"id": "u1", "text": "@alice"}},
                    {"type": "hardBreak"},
                    {"type": "status", "attrs": {"text": "INVESTIGATING"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Check gateway"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "bash"},
                "content": [{"type": "text", "text": "systemctl restart vpn"}],
            },
        ],
    }
    rendered = extract_text_from_adf(adf_doc)
    assert "## Incident Overview" in rendered
    assert "@alice" in rendered
    assert "[INVESTIGATING]" in rendered
    assert "- Check gateway" in rendered
    assert "systemctl restart vpn" in rendered


def test_strip_html_and_datetime_parsing() -> None:
    cleaned = _strip_html("<p>Hello <b>World</b>!<br/>Items:</p><ul><li>One</li></ul>")
    assert "Hello World!" in cleaned
    assert "- One" in cleaned

    dt = parse_jsm_datetime({"epochMillis": 1700000000000})
    assert dt == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_format_sla_metric_ongoing_and_completed() -> None:
    sla_ongoing = {
        "id": 30,
        "name": "Time to resolution",
        "ongoingCycle": {
            "breached": True,
            "paused": False,
            "goalDuration": {"friendly": "4h"},
            "elapsedTime": {"friendly": "6h"},
            "remainingTime": {"friendly": "-2h"},
        },
    }
    res = format_sla_metric(sla_ongoing)
    assert res is not None
    text, breached = res
    assert breached is True
    assert "status=BREACHED" in text

    sla_completed = {
        "id": 43,
        "name": "Time to first response",
        "completedCycles": [
            {
                "breached": False,
                "goalDuration": {"friendly": "15m"},
                "elapsedTime": {"friendly": "4m"},
            }
        ],
    }
    res2 = format_sla_metric(sla_completed)
    assert res2 is not None
    assert res2[1] is False
    assert "status=MET" in res2[0]


def test_extract_user_info_and_build_jql() -> None:
    user = extract_user_info(
        {"displayName": "Jane Doe", "emailAddress": "jane@acme.com"}
    )
    assert user is not None
    assert user.display_name == "Jane Doe"
    assert user.email == "jane@acme.com"

    conn = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL,
        project_key="ITSD",
        request_types=["Get IT help"],
        jql_query='priority = "High"',
    )
    jql = conn._build_jql(start=1700000000.0, end=1700003600.0)
    assert 'project = "ITSD"' in jql
    assert '"Customer Request Type" IN ("Get IT help")' in jql
    assert "updated >= 1700000000000" in jql
    assert "updated <= 1700003600000" in jql
    assert '(priority = "High")' in jql
    assert jql.endswith("ORDER BY updated ASC")


def test_convert_request_to_document_and_comment_filtering() -> None:
    conn = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL,
        project_key="ITSD",
        include_internal_comments=False,
    )
    doc = conn._convert_request_to_document(
        request_obj={
            "issueId": "1001",
            "issueKey": "ITSD-1",
            "serviceDeskId": "10",
            "requestTypeId": "25",
            "createdDate": {"epochMillis": 1700000000000},
            "reporter": {"displayName": "Alice", "emailAddress": "alice@acme.com"},
            "requestType": {"id": "25", "name": "VPN Access"},
            "requestFieldValues": [
                {"fieldId": "summary", "label": "Summary", "value": "VPN issue"},
                {"fieldId": "description", "label": "Description", "value": "Timeout"},
            ],
            "currentStatus": {"status": "Waiting for Support"},
            "_links": {"agent": f"{_BASE_URL}/browse/ITSD-1"},
        },
        comments=[
            {
                "id": "501",
                "public": True,
                "body": "Checking gateway.",
                "author": {"displayName": "Bob"},
            },
            {
                "id": "502",
                "public": False,
                "body": "Internal note.",
                "author": {"displayName": "Bob"},
            },
        ],
        slas=[
            {
                "id": "1",
                "name": "Time to first response",
                "ongoingCycle": {
                    "breached": False,
                    "paused": False,
                    "goalDuration": {"friendly": "1h"},
                },
            }
        ],
    )
    assert doc.id == f"{_BASE_URL}/browse/ITSD-1"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.metadata["issue_key"] == "ITSD-1"
    assert doc.metadata["request_type"] == "VPN Access"
    assert len(doc.sections) == 2
    assert "Checking gateway." in doc.sections[1].text


def test_registry_mapping_resolves_jsm_connector_and_config() -> None:
    from onyx.connectors.jira_service_management.config import JiraServiceManagementConnectorConfig
    from onyx.connectors.registry import CONNECTOR_CLASS_MAP

    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class is JiraServiceManagementConnectorConfig
