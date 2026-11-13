import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jira_service_management_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    build_jsm_jql_query,
    extract_jsm_metadata,
    process_jsm_issue,
)
from onyx.connectors.models import Document, HierarchyNode, SlimDocument
from onyx.connectors.planning_rule import ScopeDirection


def _make_mock_jsm_issue(
    key: str = "SD-101",
    summary: str = "VPN connection failing",
    project_key: str = "SD",
    project_name: str = "IT Service Desk",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": "User cannot connect to corporate VPN.",
            "created": "2025-05-01T10:00:00.000+0000",
            "updated": "2025-05-02T12:00:00.000+0000",
            "priority": {"name": "High"},
            "status": {"name": "Waiting for support"},
            "issuetype": {"name": "Service Request"},
            "labels": labels or [],
            "project": {
                "key": project_key,
                "name": project_name,
                "projectTypeKey": "service_desk",
            },
            "reporter": {
                "displayName": "Alice Requester",
                "emailAddress": "alice@example.com",
            },
            "assignee": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@example.com",
            },
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "bob@example.com"},
                        "body": "Investigating VPN gateway logs.",
                    }
                ]
            },
            "customfield_10010": {
                "serviceDeskId": "4",
                "requestType": {
                    "id": "17",
                    "name": "Get IT help",
                    "serviceDeskId": "4",
                },
            },
            "customfield_10011": {
                "ongoingCycle": {
                    "breached": False,
                }
            },
            "customfield_10012": [
                {
                    "id": "1",
                    "name": "Acme Corp",
                    "_links": {
                        "self": "https://jira.example.com/rest/servicedeskapi/organization/1"
                    },
                }
            ],
            "customfield_10013": [
                {
                    "accountId": "u-2",
                    "displayName": "Carol Watcher",
                    "emailAddress": "carol@example.com",
                }
            ],
        },
    }


def test_build_jsm_jql_query_defaults_to_service_desk_project_type() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2025, 1, 2, tzinfo=timezone.utc).timestamp()

    q_all = build_jsm_jql_query(project_key=None, jql_query=None, start=start, end=end)
    assert q_all.startswith('projectType = "service_desk" AND updated >=')

    q_proj = build_jsm_jql_query(project_key="SD", jql_query=None, start=start, end=end)
    assert q_proj.startswith('project = "SD" AND updated >=')

    q_custom = build_jsm_jql_query(
        project_key="SD",
        jql_query='project = "SD" AND status = "Open"',
        start=start,
        end=end,
    )
    assert q_custom.startswith('(project = "SD" AND status = "Open") AND updated >=')


def test_extract_jsm_metadata_and_process_jsm_issue() -> None:
    raw_issue = _make_mock_jsm_issue()
    meta = extract_jsm_metadata(raw_issue)
    assert meta == {
        "request_type": "Get IT help",
        "service_desk_id": "4",
        "sla_breached": "False",
        "organizations": ["Acme Corp"],
        "request_participants": ["Carol Watcher"],
    }

    # Verify a breached SLA field is not overwritten by a subsequent non-breached SLA field
    multi_sla_issue = _make_mock_jsm_issue()
    multi_sla_issue["fields"]["customfield_10011"] = {
        "ongoingCycle": {"breached": True}
    }
    multi_sla_issue["fields"]["customfield_10009"] = {
        "ongoingCycle": {"breached": False}
    }
    assert extract_jsm_metadata(multi_sla_issue)["sla_breached"] == "True"

    doc = process_jsm_issue("https://jira.example.com", raw_issue)
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://jira.example.com/browse/SD-101"
    assert doc.semantic_identifier == "SD-101: VPN connection failing"
    assert doc.metadata["request_type"] == "Get IT help"
    assert doc.metadata["service_desk_id"] == "4"
    assert doc.metadata["sla_breached"] == "False"
    assert doc.metadata["organizations"] == ["Acme Corp"]
    assert doc.metadata["request_participants"] == ["Carol Watcher"]


def test_jsm_connector_load_credentials_and_checkpoint() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com/",
        project_key="SD",
    )
    credentials = {
        "jira_user_email": "agent@example.com",
        "jira_api_token": "secret-token",
    }
    connector.load_credentials(credentials)
    assert isinstance(connector.source_operations, JiraSourceOperations)

    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = False
    mock_ops.search_issues.side_effect = [
        [_make_mock_jsm_issue("SD-101"), _make_mock_jsm_issue("SD-102")],
        [],
    ]
    connector._source_operations = mock_ops

    checkpoint = connector.build_dummy_checkpoint()
    gen = connector.load_from_checkpoint(0, time.time(), checkpoint)
    yielded: list[Any] = []
    try:
        while True:
            yielded.append(next(gen))
    except StopIteration as stop:
        next_cp = stop.value

    docs = [item for item in yielded if isinstance(item, Document)]
    nodes = [item for item in yielded if isinstance(item, HierarchyNode)]
    assert len(docs) == 2
    assert len(nodes) == 1
    assert all(d.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for d in docs)
    assert next_cp.has_more is False

    mock_ops.search_issues.side_effect = None
    mock_ops.search_issues.return_value = [
        _make_mock_jsm_issue("SD-101"),
        _make_mock_jsm_issue("SD-102"),
    ]
    slim_batches = list(connector.retrieve_all_slim_docs(0, time.time()))
    slim_docs = [
        item
        for batch in slim_batches
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    assert [s.id for s in slim_docs] == [
        "https://jira.example.com/browse/SD-101",
        "https://jira.example.com/browse/SD-102",
    ]


def test_jsm_server_dc_resolves_service_desk_projects() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = False
    mock_ops.list_projects.return_value = [
        {"key": "SD", "projectTypeKey": "service_desk"},
        {"key": "ENG", "projectTypeKey": "software"},
        {"key": "NO_TYPE"},
    ]
    mock_ops.get_project.return_value = {"key": "NO_TYPE", "projectTypeKey": "software"}
    connector._source_operations = mock_ops

    jql = connector._get_jql_query(0, 100)
    assert jql.startswith('project in ("SD") AND updated >=')

    # Verify list_projects() errors are converted to typed connector exceptions on Server/DC path
    failing_connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    failing_ops = MagicMock(spec=JiraSourceOperations)
    failing_ops._is_cloud.return_value = False
    failing_ops.list_projects.side_effect = JiraApiError("unauth", status_code=401)
    failing_connector._source_operations = failing_ops
    with pytest.raises(CredentialExpiredError):
        failing_connector._get_jql_query(0, 100)


def test_jsm_validate_connector_settings() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="SD",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = True
    connector._source_operations = mock_ops

    mock_ops.get_project.return_value = {"key": "SD", "projectTypeKey": "service_desk"}
    connector.validate_connector_settings()

    mock_ops.get_project.return_value = {"key": "ENG", "projectTypeKey": "software"}
    with pytest.raises(ConnectorValidationError, match="expected 'service_desk'"):
        connector.validate_connector_settings()

    mock_ops.get_project.return_value = {"key": "UNKNOWN"}
    with pytest.raises(ConnectorValidationError, match="expected 'service_desk'"):
        connector.validate_connector_settings()

    mock_ops.get_project.side_effect = JiraApiError("unauth", status_code=401)
    with pytest.raises(CredentialExpiredError):
        connector.validate_connector_settings()

    mock_ops.get_project.side_effect = JiraApiError("forbidden", status_code=403)
    with pytest.raises(InsufficientPermissionsError):
        connector.validate_connector_settings()

    # Cloud no-project validation path: list_projects() failures raise typed connector errors
    cloud_all_connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    cloud_ops = MagicMock(spec=JiraSourceOperations)
    cloud_ops._is_cloud.return_value = True
    cloud_ops.list_projects.side_effect = JiraApiError("unauth", status_code=401)
    cloud_all_connector._source_operations = cloud_ops
    with pytest.raises(CredentialExpiredError):
        cloud_all_connector.validate_connector_settings()

    cloud_ops.list_projects.side_effect = JiraApiError("forbidden", status_code=403)
    with pytest.raises(InsufficientPermissionsError):
        cloud_all_connector.validate_connector_settings()


def test_jsm_config_and_planning_rule() -> None:
    cfg1 = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="SD",
        jql_query='project = "SD"',
    )
    cfg2 = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="OTHER",
        jql_query='project = "SD"',
    )
    override = jira_service_management_planning_rule(cfg1, cfg2)
    assert override is not None
    assert override.scope_directions == {"project_key": ScopeDirection.NONE}

    # Whitespace-only jql_query is treated as unset
    cfg_blank = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="OTHER",
        jql_query="   ",
    )
    assert jira_service_management_planning_rule(cfg1, cfg_blank) is None
