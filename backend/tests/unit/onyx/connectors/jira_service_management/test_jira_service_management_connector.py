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
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)
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
                "_links": {
                    "web": "https://jira.example.com/servicedesk/customer/portal/4/SD-101"
                },
                "currentStatus": {
                    "status": "Waiting for support",
                },
                "requestType": {
                    "id": "17",
                    "name": "Get IT help",
                    "serviceDeskId": "4",
                },
            },
            "customfield_10011": {
                "name": "Time to first response",
                "ongoingCycle": {
                    "breached": False,
                },
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
            "customfield_10014": [
                {
                    "id": "99",
                    "name": "Manager Approval",
                    "finalDecision": "approved",
                    "approvers": [],
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
    issue = _make_mock_jsm_issue()
    meta = extract_jsm_metadata(issue)
    assert meta["request_type"] == "Get IT help"
    assert meta["service_desk_id"] == "4"
    assert (
        meta["customer_request_url"]
        == "https://jira.example.com/servicedesk/customer/portal/4/SD-101"
    )
    assert meta["customer_status"] == "Waiting for support"
    assert meta["sla_breached"] == "False"
    assert meta["sla_summary"] == ["Time to first response: Within SLA"]
    assert meta["organizations"] == ["Acme Corp"]
    assert meta["request_participants"] == ["Carol Watcher"]
    assert meta["approvals"] == ["Manager Approval: approved"]

    doc = process_jsm_issue(
        jira_base_url="https://jira.example.com",
        issue=issue,
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://jira.example.com/browse/SD-101"
    assert doc.metadata["request_type"] == "Get IT help"
    assert doc.metadata["service_desk_id"] == "4"
    assert doc.metadata["organizations"] == ["Acme Corp"]
    assert doc.metadata["request_participants"] == ["Carol Watcher"]
    assert doc.metadata["approvals"] == ["Manager Approval: approved"]
    assert doc.metadata["priority"] == "High"
    assert doc.metadata["status"] == "Waiting for support"


def test_extract_jsm_metadata_multiple_slas_combines_breach_flag() -> None:
    issue = _make_mock_jsm_issue()
    # First SLA is breached, second SLA is not breached -> overall sla_breached must remain "True"
    issue["fields"]["customfield_10011"] = {
        "name": "Time to first response",
        "completedCycles": [{"breached": True}],
    }
    issue["fields"]["customfield_10020"] = {
        "name": "Time to resolution",
        "ongoingCycle": {"breached": False},
    }
    meta = extract_jsm_metadata(issue)
    assert meta["sla_breached"] == "True"
    assert meta["sla_summary"] == [
        "Time to first response: Breached",
        "Time to resolution: Within SLA",
    ]


def test_jsm_checkpointed_load_and_slim_docs() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="SD",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = False
    mock_ops.search_issues.return_value = [_make_mock_jsm_issue()]
    connector._source_operations = mock_ops

    checkpoint = connector.build_dummy_checkpoint()
    gen = connector.load_from_checkpoint(start=0, end=time.time(), checkpoint=checkpoint)
    yielded = list(gen)

    nodes = [item for item in yielded if isinstance(item, HierarchyNode)]
    docs = [item for item in yielded if isinstance(item, Document)]

    assert len(nodes) == 1
    assert nodes[0].raw_node_id == "SD"
    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert docs[0].metadata["request_type"] == "Get IT help"

    slim_batches = list(connector.retrieve_all_slim_docs(start=0, end=time.time()))
    slim_docs = [
        item
        for batch in slim_batches
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    assert len(slim_docs) == 1
    assert slim_docs[0].id == "https://jira.example.com/browse/SD-101"


def test_jsm_server_default_scope_resolves_service_desk_projects() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = False
    mock_ops.list_projects.return_value = [
        {"key": "ENG", "projectTypeKey": "software"},
        {"key": "SD", "projectTypeKey": "service_desk"},
        {"key": "ITSM", "projectTypeKey": "service_desk"},
    ]
    connector._source_operations = mock_ops

    jql = connector._get_jql_query(start=1, end=2)
    assert jql == 'project in ("SD", "ITSM") AND updated >= 1000 AND updated <= 2000'


def test_jsm_server_default_scope_fails_reindex_before_batch_catch() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops._is_cloud.return_value = False
    mock_ops.list_projects.return_value = [
        {"key": "ENG", "projectTypeKey": "software"},
    ]
    connector._source_operations = mock_ops

    failures = [
        ConnectorFailure(
            failed_document=DocumentFailure(
                document_id="https://jira.example.com/browse/SD-101",
                document_link="https://jira.example.com/browse/SD-101",
            ),
            failure_message="previous error",
        )
    ]
    with pytest.raises(ConnectorValidationError, match="No Jira Service Management"):
        list(connector.reindex(failures))


def test_jsm_validate_connector_settings() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="SD",
    )
    mock_ops = MagicMock(spec=JiraSourceOperations)
    mock_ops.get_project.return_value = {
        "key": "SD",
        "projectTypeKey": "service_desk",
    }
    connector._source_operations = mock_ops

    # Valid service_desk project passes
    connector.validate_connector_settings()

    # Non-service_desk project raises ConnectorValidationError
    mock_ops.get_project.return_value = {
        "key": "ENG",
        "projectTypeKey": "software",
    }
    with pytest.raises(ConnectorValidationError, match="expected 'service_desk'"):
        connector.validate_connector_settings()

    # Expired credential raises CredentialExpiredError
    mock_ops.get_project.side_effect = JiraApiError("Unauthorized", status_code=401)
    with pytest.raises(CredentialExpiredError):
        connector.validate_connector_settings()

    # Forbidden raises InsufficientPermissionsError
    mock_ops.get_project.side_effect = JiraApiError("Forbidden", status_code=403)
    with pytest.raises(InsufficientPermissionsError):
        connector.validate_connector_settings()


def test_jsm_planning_rule_ignores_project_when_jql_set() -> None:
    old_cfg = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="SD1",
        jql_query='project = "SD"',
    )
    new_cfg = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="SD2",
        jql_query='project = "SD"',
    )
    override = jira_service_management_planning_rule(old_cfg, new_cfg)
    assert override is not None
    assert override.scope_directions == {"project_key": ScopeDirection.NONE}

    # Whitespace-only jql_query is treated as unset
    blank_jql_cfg = JiraServiceManagementConnectorConfig(
        jira_base_url="https://jira.example.com",
        project_key="SD2",
        jql_query="   ",
    )
    assert jira_service_management_planning_rule(old_cfg, blank_jql_cfg) is None
