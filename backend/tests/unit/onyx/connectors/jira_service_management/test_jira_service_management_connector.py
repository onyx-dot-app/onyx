from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    is_credential_usable_for_source,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.field_policy import ScopeDirection
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.jira_service_management.client import (
    JiraServiceManagementClient,
    JiraServiceManagementClientError,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jira_service_management_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.models import (
    JiraServiceManagementCheckpoint,
)
from onyx.connectors.jira_service_management.utils import (
    build_jsm_browse_url,
    build_jsm_portal_url,
    extract_attachments_from_issue,
    extract_changelog_entries,
    extract_comments_from_issue_fields,
    extract_comments_from_jsm_payload,
    extract_rich_text,
    extract_sla_from_issue_fields,
    extract_sla_metrics_from_jsm_payload,
    extract_text_from_adf,
    format_changelog_section,
    format_comments_section,
    format_sla_section,
    parse_jsm_datetime,
    populate_sla_metadata,
)
from onyx.connectors.models import Document, HierarchyNode, SlimDocument


# ---------------------------------------------------------------------------
# Sample Fixtures
# ---------------------------------------------------------------------------


def _sample_service_desks() -> list[dict[str, Any]]:
    return [
        {
            "id": "1",
            "projectId": "10001",
            "projectName": "IT Service Desk",
            "projectKey": "ITSM",
            "_links": {
                "portal": "https://acme.atlassian.net/servicedesk/customer/portal/1"
            },
        },
        {
            "id": "2",
            "projectId": "10002",
            "projectName": "HR Service Desk",
            "projectKey": "HRSD",
            "_links": {
                "portal": "https://acme.atlassian.net/servicedesk/customer/portal/2"
            },
        },
    ]


def _sample_issue(
    key: str = "ITSM-101",
    summary: str = "VPN connection failing on macOS",
    labels: list[str] | None = None,
    updated: str = "2025-03-15T12:30:00.000+0000",
) -> dict[str, Any]:
    return {
        "id": "20001",
        "key": key,
        "fields": {
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "User cannot connect to corporate VPN from macOS Sequoia.",
                            }
                        ],
                    },
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "bash"},
                        "content": [
                            {
                                "type": "text",
                                "text": "vpn-cli connect --profile prod",
                            }
                        ],
                    },
                ],
            },
            "project": {
                "id": "10001",
                "key": "ITSM",
                "name": "IT Service Desk",
            },
            "issuetype": {"name": "Service Request"},
            "status": {
                "name": "Waiting for support",
                "statusCategory": {"name": "In Progress"},
            },
            "priority": {"name": "High"},
            "resolution": None,
            "reporter": {
                "displayName": "Alice Customer",
                "emailAddress": "alice@customer.com",
            },
            "assignee": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@acme.com",
            },
            "creator": {
                "displayName": "Alice Customer",
                "emailAddress": "alice@customer.com",
            },
            "labels": labels or ["vpn", "macos"],
            "components": [{"name": "Networking"}],
            "created": "2025-03-15T10:00:00.000+0000",
            "updated": updated,
            "attachment": [
                {
                    "id": "att-1",
                    "filename": "vpn_error.log",
                    "mimeType": "text/plain",
                    "size": 42,
                    "created": "2025-03-15T10:05:00.000+0000",
                    "author": {"displayName": "Alice Customer"},
                    "content": "https://acme.atlassian.net/secure/attachment/att-1/vpn_error.log",
                }
            ],
        },
    }


def _sample_jsm_request(key: str = "ITSM-101") -> dict[str, Any]:
    return {
        "issueId": "20001",
        "issueKey": key,
        "serviceDeskId": "1",
        "requestType": {
            "id": "15",
            "name": "Get IT help",
            "description": "General IT support",
        },
        "currentStatus": {
            "status": "Waiting for support",
            "statusCategory": "INDETERMINATE",
            "statusDate": {
                "iso8601": "2025-03-15T12:30:00+0000",
                "epochMillis": 1742041800000,
            },
        },
        "participants": {
            "values": [
                {
                    "displayName": "Charlie Manager",
                    "emailAddress": "charlie@customer.com",
                }
            ]
        },
        "organizations": {
            "values": [
                {"id": "10", "name": "Enterprise Corp"},
            ]
        },
    }


def _sample_slas() -> list[dict[str, Any]]:
    return [
        {
            "id": "1",
            "name": "Time to first response",
            "completedCycles": [
                {
                    "startTime": {"iso8601": "2025-03-15T10:00:00+0000"},
                    "stopTime": {"iso8601": "2025-03-15T10:12:00+0000"},
                    "breached": False,
                    "goalDuration": {"friendly": "30m", "millis": 1800000},
                    "elapsedTime": {"friendly": "12m", "millis": 720000},
                    "remainingTime": {"friendly": "18m", "millis": 1080000},
                }
            ],
        },
        {
            "id": "2",
            "name": "Time to resolution",
            "completedCycles": [],
            "ongoingCycle": {
                "startTime": {"iso8601": "2025-03-15T10:00:00+0000"},
                "breachTime": {"iso8601": "2025-03-15T14:00:00+0000"},
                "breached": True,
                "paused": False,
                "withinCalendarHours": True,
                "goalDuration": {"friendly": "4h", "millis": 14400000},
                "elapsedTime": {"friendly": "4h 30m", "millis": 16200000},
                "remainingTime": {"friendly": "-30m", "millis": -1800000},
            },
        },
    ]


def _sample_jsm_comments() -> list[dict[str, Any]]:
    return [
        {
            "id": "c-1",
            "body": "We are checking the VPN concentrator logs.",
            "public": True,
            "author": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@acme.com",
            },
            "created": {"iso8601": "2025-03-15T10:12:00+0000"},
        },
        {
            "id": "c-2",
            "body": "Internal note: firewall rule 402 was modified yesterday.",
            "public": False,
            "author": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@acme.com",
            },
            "created": {"iso8601": "2025-03-15T10:20:00+0000"},
        },
        {
            "id": "c-3",
            "body": "Automated bot ping.",
            "public": True,
            "author": {
                "displayName": "Automation Bot",
                "emailAddress": "bot@acme.com",
            },
            "created": {"iso8601": "2025-03-15T10:25:00+0000"},
        },
    ]


def _sample_changelog() -> list[dict[str, Any]]:
    return [
        {
            "id": "hist-1",
            "author": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@acme.com",
            },
            "created": "2025-03-15T10:15:00.000+0000",
            "items": [
                {
                    "field": "status",
                    "fromString": "Open",
                    "toString": "Waiting for support",
                },
                {
                    "field": "priority",
                    "fromString": "Medium",
                    "toString": "High",
                },
            ],
        }
    ]


# ---------------------------------------------------------------------------
# 1. Config, Credential Family & Planning Rule Tests
# ---------------------------------------------------------------------------


def test_jsm_planning_rule_ignores_scope_fields_when_jql_query_active() -> None:
    old = JiraServiceManagementConnectorConfig(
        jira_service_management_base_url="https://acme.atlassian.net",
        jql_query='project = "ITSM"',
        project_key="OLD",
        service_desk_ids=["1"],
    )
    new = JiraServiceManagementConnectorConfig(
        jira_service_management_base_url="https://acme.atlassian.net",
        jql_query='project = "ITSM"',
        project_key="NEW",
        service_desk_ids=["1", "2"],
    )
    override = jira_service_management_planning_rule(old, new)
    assert override is not None
    assert override.scope_directions == {
        "project_key": ScopeDirection.NONE,
        "service_desk_ids": ScopeDirection.NONE,
        "queue_ids": ScopeDirection.NONE,
        "request_types": ScopeDirection.NONE,
    }


def test_jsm_planning_rule_returns_none_without_jql_query() -> None:
    old = JiraServiceManagementConnectorConfig(
        jira_service_management_base_url="https://acme.atlassian.net",
        project_key="ITSM",
    )
    new = JiraServiceManagementConnectorConfig(
        jira_service_management_base_url="https://acme.atlassian.net",
        project_key="HRSD",
    )
    assert jira_service_management_planning_rule(old, new) is None


def test_atlassian_credential_family_round_trips_for_jsm() -> None:
    stored = to_stored_credential_json(
        DocumentSource.JIRA_SERVICE_MANAGEMENT,
        {"jira_user_email": "agent@acme.com", "jira_api_token": "secret-tok"},
        None,
    )
    assert is_credential_usable_for_source(
        DocumentSource.JIRA_SERVICE_MANAGEMENT,
        stored,
        DocumentSource.JIRA,
    )
    assert is_credential_usable_for_source(
        DocumentSource.JIRA,
        stored,
        DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )
    assert to_source_credential_json(
        DocumentSource.JIRA_SERVICE_MANAGEMENT, stored
    ) == {
        "jira_user_email": "agent@acme.com",
        "jira_api_token": "secret-tok",
    }


# ---------------------------------------------------------------------------
# 2. Client Authentication, Pagination & Error Handling Tests
# ---------------------------------------------------------------------------


def test_client_cloud_vs_datacenter_auth_and_version_detection() -> None:
    cloud_client = JiraServiceManagementClient(
        base_url="https://acme.atlassian.net/",
        api_token="cloud-token",
        user_email="agent@acme.com",
    )
    assert cloud_client.base_url == "https://acme.atlassian.net"
    assert cloud_client.api_version == "3"
    assert cloud_client.session.auth == ("agent@acme.com", "cloud-token")
    assert cloud_client.session.headers.get("X-ExperimentalApi") == "opt-in"

    dc_client = JiraServiceManagementClient(
        base_url="https://jira.internal.corp",
        api_token="dc-pat-token",
        user_email=None,
    )
    assert dc_client.api_version == "2"
    assert dc_client.session.auth is None
    assert dc_client.session.headers.get("Authorization") == "Bearer dc-pat-token"


@patch("onyx.connectors.jira_service_management.client.scoped_url")
def test_client_scoped_token_resolves_gateway_url(mock_scoped_url: MagicMock) -> None:
    mock_scoped_url.return_value = "https://api.atlassian.com/ex/jira/cloud-123"
    client = JiraServiceManagementClient(
        base_url="https://acme.atlassian.net",
        api_token="scoped-token",
        user_email="agent@acme.com",
        scoped_token=True,
    )
    assert client.base_url == "https://api.atlassian.com/ex/jira/cloud-123"
    assert client.original_base_url == "https://acme.atlassian.net"
    mock_scoped_url.assert_called_once_with("https://acme.atlassian.net", "jira")


def test_client_paginate_servicedesk_api_multi_page() -> None:
    session = MagicMock(spec=requests.Session)
    session.headers = {}

    resp_page_1 = MagicMock(spec=requests.Response)
    resp_page_1.status_code = 200
    resp_page_1.content = b"{}"
    resp_page_1.json.return_value = {
        "size": 2,
        "start": 0,
        "limit": 2,
        "isLastPage": False,
        "values": [{"id": "1"}, {"id": "2"}],
    }

    resp_page_2 = MagicMock(spec=requests.Response)
    resp_page_2.status_code = 200
    resp_page_2.content = b"{}"
    resp_page_2.json.return_value = {
        "size": 1,
        "start": 2,
        "limit": 2,
        "isLastPage": True,
        "values": [{"id": "3"}],
    }

    session.request.side_effect = [resp_page_1, resp_page_2]
    client = JiraServiceManagementClient(
        base_url="https://acme.atlassian.net",
        api_token="tok",
        user_email="a@b.com",
        session=session,
    )

    items = list(
        client.paginate_servicedesk_api("/rest/servicedeskapi/servicedesk", limit=2)
    )
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert session.request.call_count == 2


def test_client_error_extracts_jira_error_messages() -> None:
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    err_resp = MagicMock(spec=requests.Response)
    err_resp.status_code = 400
    err_resp.text = '{"errorMessages":["Field project does not exist"]}'
    err_resp.json.return_value = {
        "errorMessages": ["Field project does not exist"]
    }
    session.request.return_value = err_resp

    client = JiraServiceManagementClient(
        base_url="https://acme.atlassian.net",
        api_token="tok",
        user_email="a@b.com",
        session=session,
    )
    with pytest.raises(JiraServiceManagementClientError) as exc_info:
        client.get_service_desk_info()
    assert exc_info.value.status_code == 400
    assert "Field project does not exist" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Utils Extraction & Formatting Tests
# ---------------------------------------------------------------------------


def test_extract_text_from_adf_and_html() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Incident Summary"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Affected host: "},
                                    {
                                        "type": "inlineCard",
                                        "attrs": {"url": "https://status.acme.com"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    extracted = extract_text_from_adf(adf)
    assert "Incident Summary" in extracted
    assert "https://status.acme.com" in extracted

    html_text = extract_rich_text("<p>Hello <b>world</b><br/>Line 2</p>")
    assert "Hello" in html_text
    assert "world" in html_text
    assert "Line 2" in html_text


def test_parse_jsm_datetime_handles_jsm_date_dict_and_iso() -> None:
    dt1 = parse_jsm_datetime(
        {"iso8601": "2025-03-15T12:30:00+0000", "epochMillis": 1742041800000}
    )
    assert dt1 == datetime(2025, 3, 15, 12, 30, tzinfo=timezone.utc)

    dt2 = parse_jsm_datetime({"epochMillis": 1742041800000})
    assert dt2 == datetime(2025, 3, 15, 12, 30, tzinfo=timezone.utc)

    dt3 = parse_jsm_datetime("2025-03-15T12:30:00.000+0000")
    assert dt3 == datetime(2025, 3, 15, 12, 30, tzinfo=timezone.utc)


def test_sla_extraction_formatting_and_metadata() -> None:
    metrics = extract_sla_metrics_from_jsm_payload(_sample_slas())
    assert len(metrics) == 2
    assert metrics[0].name == "Time to first response"
    assert metrics[0].breached is False
    assert metrics[0].status == "MET"
    assert metrics[0].elapsed_friendly == "12m"

    assert metrics[1].name == "Time to resolution"
    assert metrics[1].breached is True
    assert metrics[1].ongoing is True
    assert metrics[1].status == "BREACHED (IN_PROGRESS)"

    section_text = format_sla_section(metrics)
    assert "Time to first response: MET" in section_text
    assert "Time to resolution: BREACHED (IN_PROGRESS) [BREACHED]" in section_text

    meta: dict[str, str | list[str]] = {}
    populate_sla_metadata(metrics, meta)
    assert meta["sla_breached"] == "true"
    assert meta["sla_status"] == "BREACHED"
    assert meta["sla_time_to_first_response"] == "MET"
    assert meta["sla_time_to_resolution"] == "BREACHED (IN_PROGRESS)"


def test_comment_extraction_respects_internal_flag_and_blacklist() -> None:
    raw_comments = _sample_jsm_comments()

    # Include internal, blacklist bot@acme.com
    comments_with_internal = extract_comments_from_jsm_payload(
        raw_comments,
        include_internal=True,
        email_blacklist={"bot@acme.com"},
    )
    assert len(comments_with_internal) == 2
    assert comments_with_internal[0].public is True
    assert comments_with_internal[1].public is False

    formatted = format_comments_section(comments_with_internal)
    assert "[Public Reply]" in formatted
    assert "[Internal Note]" in formatted
    assert "Automation Bot" not in formatted

    # Exclude internal comments
    public_only = extract_comments_from_jsm_payload(
        raw_comments,
        include_internal=False,
        email_blacklist={"bot@acme.com"},
    )
    assert len(public_only) == 1
    assert public_only[0].public is True
    assert "firewall rule 402" not in format_comments_section(public_only)


def test_url_builders() -> None:
    assert (
        build_jsm_browse_url("https://acme.atlassian.net/", "ITSM-101")
        == "https://acme.atlassian.net/browse/ITSM-101"
    )
    assert (
        build_jsm_portal_url("https://acme.atlassian.net/", "1", "ITSM-101")
        == "https://acme.atlassian.net/servicedesk/customer/portal/1/ITSM-101"
    )


# ---------------------------------------------------------------------------
# 4. Connector Validation & JQL Building Tests
# ---------------------------------------------------------------------------


def _build_connector_with_mock_client(**kwargs: Any) -> tuple[JiraServiceManagementConnector, MagicMock]:
    connector = JiraServiceManagementConnector(
        jira_service_management_base_url=kwargs.pop(
            "jira_service_management_base_url", "https://acme.atlassian.net"
        ),
        **kwargs,
    )
    mock_client = MagicMock(spec=JiraServiceManagementClient)
    mock_client.list_service_desks.return_value = _sample_service_desks()
    connector._client = mock_client
    return connector, mock_client


def test_validate_connector_settings_success_and_errors() -> None:
    # 1. Invalid URL
    bad_url_conn, _ = _build_connector_with_mock_client(
        jira_service_management_base_url="ftp://invalid-url"
    )
    with pytest.raises(ConnectorValidationError):
        bad_url_conn.validate_connector_settings()

    # 2. HTTP 401 -> CredentialExpiredError
    conn_401, client_401 = _build_connector_with_mock_client()
    client_401.get_service_desk_info.side_effect = JiraServiceManagementClientError(
        "Unauthorized", status_code=401
    )
    with pytest.raises(CredentialExpiredError):
        conn_401.validate_connector_settings()

    # 3. HTTP 403 -> InsufficientPermissionsError
    conn_403, client_403 = _build_connector_with_mock_client()
    client_403.get_service_desk_info.side_effect = JiraServiceManagementClientError(
        "Forbidden", status_code=403
    )
    with pytest.raises(InsufficientPermissionsError):
        conn_403.validate_connector_settings()

    # 4. Missing queue_ids -> ConnectorValidationError
    conn_q, client_q = _build_connector_with_mock_client(
        service_desk_ids=["1"],
        queue_ids=["999"],
    )
    client_q.list_queues.return_value = [{"id": "10", "name": "All Open"}]
    with pytest.raises(ConnectorValidationError, match="999"):
        conn_q.validate_connector_settings()

    # 5. Valid settings with service desk + queue
    conn_ok, client_ok = _build_connector_with_mock_client(
        service_desk_ids=["1"],
        queue_ids=["10"],
    )
    client_ok.list_queues.return_value = [{"id": "10", "name": "All Open"}]
    conn_ok.validate_connector_settings()


def test_build_jql_query_combinations() -> None:
    # Default: all service desk projects
    conn_default, _ = _build_connector_with_mock_client()
    assert (
        conn_default.build_jql_query()
        == 'projectType = "service_desk" ORDER BY updated ASC, key ASC'
    )

    # With service_desk_ids and request_types
    conn_scoped, _ = _build_connector_with_mock_client(
        service_desk_ids=["1", "2"],
        request_types=["Get IT help", "Report a system problem"],
    )
    jql = conn_scoped.build_jql_query(start=1742000000, end=1742086400)
    assert 'project IN ("ITSM", "HRSD")' in jql
    assert '"Customer Request Type" IN ("Get IT help", "Report a system problem")' in jql
    assert "updated >= 1742000000000" in jql
    assert jql.endswith("ORDER BY updated ASC, key ASC")

    # Custom JQL with ORDER BY preserved
    conn_custom, _ = _build_connector_with_mock_client(
        jql_query='project = "ITSM" AND priority = High ORDER BY created DESC'
    )
    custom_jql = conn_custom.build_jql_query(start=1742000000)
    assert custom_jql.startswith('(project = "ITSM" AND priority = High) AND updated >=')
    assert custom_jql.endswith("ORDER BY created DESC")


# ---------------------------------------------------------------------------
# 5. End-to-End Indexing, Queue Mode, Checkpointing & Slim Docs Tests
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_indexes_full_jsm_ticket_with_sla_comments_changelog_and_attachments() -> None:
    connector, mock_client = _build_connector_with_mock_client(
        project_key="ITSM",
        comment_email_blacklist=["bot@acme.com"],
        include_internal_comments=True,
        include_sla=True,
        include_changelog=True,
        include_attachments=True,
    )

    mock_client.search_jql_page.return_value = (
        [_sample_issue("ITSM-101")],
        None,
        1,
    )
    mock_client.get_customer_request.return_value = _sample_jsm_request("ITSM-101")
    mock_client.get_request_sla.return_value = _sample_slas()
    mock_client.get_request_comments.return_value = _sample_jsm_comments()
    mock_client.get_issue_changelog.return_value = _sample_changelog()
    mock_client.download_attachment.return_value = b"ERROR: TLS handshake timeout on gateway"

    checkpoint = connector.build_dummy_checkpoint()
    gen = connector.load_from_checkpoint(start=0, end=2000000000, checkpoint=checkpoint)

    emitted: list[Document | HierarchyNode | ConnectorFailure] = []
    try:
        while True:
            emitted.append(next(gen))
    except StopIteration as stop:
        final_checkpoint = stop.value

    assert final_checkpoint.has_more is False
    assert final_checkpoint.seen_issue_keys == []

    hierarchy_nodes = [x for x in emitted if isinstance(x, HierarchyNode)]
    docs = [x for x in emitted if isinstance(x, Document)]
    assert len(hierarchy_nodes) == 1
    assert hierarchy_nodes[0].raw_node_id == "ITSM"
    assert hierarchy_nodes[0].display_name == "IT Service Desk"

    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "https://acme.atlassian.net/browse/ITSM-101"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "ITSM-101: VPN connection failing on macOS"
    assert doc.parent_hierarchy_raw_node_id == "ITSM"

    # Metadata verification
    assert doc.metadata["issue_key"] == "ITSM-101"
    assert doc.metadata["project"] == "ITSM"
    assert doc.metadata["service_desk_id"] == "1"
    assert doc.metadata["request_type"] == "Get IT help"
    assert doc.metadata["status"] == "Waiting for support"
    assert doc.metadata["priority"] == "High"
    assert doc.metadata["sla_breached"] == "true"
    assert doc.metadata["sla_status"] == "BREACHED"
    assert doc.metadata["organizations"] == ["Enterprise Corp"]

    # Sections verification (Overview, SLA, Comments, Changelog, Attachments)
    assert len(doc.sections) == 5
    full_text = "\n\n".join(s.text for s in doc.sections if s.text)
    assert "User cannot connect to corporate VPN from macOS Sequoia." in full_text
    assert "vpn-cli connect --profile prod" in full_text
    assert "Time to first response: MET" in full_text
    assert "Time to resolution: BREACHED (IN_PROGRESS) [BREACHED]" in full_text
    assert "[Public Reply]" in full_text
    assert "[Internal Note]" in full_text
    assert "Automation Bot" not in full_text
    assert "status: 'Open' -> 'Waiting for support'" in full_text
    assert "vpn_error.log" in full_text
    assert "ERROR: TLS handshake timeout on gateway" in full_text


def test_queue_mode_indexing_and_deduplication() -> None:
    connector, mock_client = _build_connector_with_mock_client(
        service_desk_ids=["1"],
        queue_ids=["10", "11"],
        include_sla=False,
        include_changelog=False,
    )
    mock_client.list_queues.return_value = [
        {"id": "10", "name": "Unassigned Incidents"},
        {"id": "11", "name": "High Priority Queue"},
    ]
    # Both queues contain ITSM-101; queue 11 also contains ITSM-102
    mock_client._get_json.side_effect = [
        {
            "isLastPage": True,
            "values": [_sample_issue("ITSM-101")],
        },
        {
            "isLastPage": True,
            "values": [
                _sample_issue("ITSM-101"),
                _sample_issue("ITSM-102", summary="Laptop screen flickering"),
            ],
        },
    ]
    mock_client.get_customer_request.side_effect = lambda key, **_: _sample_jsm_request(key)
    mock_client.get_request_comments.return_value = []

    batches = list(connector.load_from_state())
    all_docs = [item for batch in batches for item in batch if isinstance(item, Document)]
    assert [d.metadata["issue_key"] for d in all_docs] == ["ITSM-101", "ITSM-102"]
    assert all_docs[0].metadata["queue_id"] == "10"
    assert all_docs[0].metadata["queue_name"] == "Unassigned Incidents"
    assert all_docs[1].metadata["queue_id"] == "11"
    assert all_docs[1].metadata["queue_name"] == "High Priority Queue"


def test_labels_to_skip_filters_out_matching_issues() -> None:
    connector, mock_client = _build_connector_with_mock_client(
        labels_to_skip=["secret-do-not-index"],
        include_sla=False,
        include_changelog=False,
    )
    mock_client.search_jql_page.return_value = (
        [
            _sample_issue("ITSM-101", labels=["secret-do-not-index"]),
            _sample_issue("ITSM-102", labels=["public"]),
        ],
        None,
        2,
    )
    mock_client.get_customer_request.return_value = _sample_jsm_request("ITSM-102")
    mock_client.get_request_comments.return_value = []

    batches = list(connector.load_from_state())
    all_docs = [item for batch in batches for item in batch if isinstance(item, Document)]
    assert len(all_docs) == 1
    assert all_docs[0].metadata["issue_key"] == "ITSM-102"


def test_fallback_to_customer_requests_when_jql_forbidden() -> None:
    connector, mock_client = _build_connector_with_mock_client(
        service_desk_ids=["1"],
        include_sla=False,
        include_changelog=False,
    )
    mock_client.search_jql_page.side_effect = JiraServiceManagementClientError(
        "Forbidden JQL", status_code=403
    )
    req = _sample_jsm_request("ITSM-500")
    req["requestFieldValues"] = [
        {"fieldId": "summary", "value": "Portal-only request"},
        {"fieldId": "description", "value": "Submitted via customer portal"},
    ]
    mock_client._get_json.return_value = {
        "isLastPage": True,
        "values": [req],
    }
    mock_client.get_issue.return_value = {"key": "ITSM-500", "fields": {"labels": []}}
    mock_client.get_request_comments.return_value = []

    batches = list(connector.load_from_state())
    all_docs = [item for batch in batches for item in batch if isinstance(item, Document)]
    assert len(all_docs) == 1
    assert all_docs[0].id == "https://acme.atlassian.net/browse/ITSM-500"
    assert "Portal-only request" in all_docs[0].semantic_identifier


def test_retrieve_all_slim_docs_and_perm_sync() -> None:
    connector, mock_client = _build_connector_with_mock_client(project_key="ITSM")
    mock_client.search_jql_page.return_value = (
        [_sample_issue("ITSM-101"), _sample_issue("ITSM-102")],
        None,
        2,
    )
    callback_batches: list[list[SlimDocument]] = []
    slim_batches = list(
        connector.retrieve_all_slim_docs_perm_sync(
            callback=lambda b: callback_batches.append(b)
        )
    )
    assert len(slim_batches) == 1
    assert len(slim_batches[0]) == 2
    assert isinstance(slim_batches[0][0], SlimDocument)
    assert slim_batches[0][0].id == "https://acme.atlassian.net/browse/ITSM-101"
    assert slim_batches[0][0].parent_hierarchy_raw_node_id == "ITSM"
    assert len(callback_batches) == 1
