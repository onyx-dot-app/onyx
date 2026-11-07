"""Unit tests for the Jira Service Management connector.

Covers the two things the connector changes on top of the Jira connector:
documents are stamped with the JSM document source, and their metadata gains
the JSM portal fields (request type, portal status, SLA breach summary) when
the Service Desk API answers - with every enrichment failure swallowed so an
indexing run never breaks on JSM being unavailable.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import _SERVICEDESK_BASE_URL
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _sla_breached_summary,
)
from onyx.connectors.models import Document


def _make_issue(key: str, project_key: str = "HELP") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "project": {
                "key": project_key,
                "name": "Help Desk",
                "projectTypeKey": "service_desk",
            },
            "summary": f"Summary for {key}",
            "description": None,
            "comment": {"comments": []},
            "parent": None,
            "labels": [],
            "created": "2026-01-01T12:00:00.000+0000",
            "updated": "2026-01-02T12:00:00.000+0000",
        },
    }


def _documents(
    connector: JiraServiceManagementConnector, issue: dict[str, Any]
) -> list[Document]:
    with (
        patch.object(
            JiraConnector, "_yield_project_hierarchy_node", return_value=iter([])
        ),
        patch.object(
            JiraConnector,
            "_yield_parent_hierarchy_node_if_epic",
            return_value=iter([]),
        ),
        patch.object(
            JiraConnector, "_yield_epic_hierarchy_node", return_value=iter([])
        ),
        patch.object(JiraConnector, "_is_epic", return_value=False),
        patch.object(
            JiraConnector, "_get_parent_hierarchy_raw_node_id", return_value=None
        ),
    ):
        return [
            item
            for item in connector._issue_to_items(
                issue, set(), include_permissions=False
            )
            if isinstance(item, Document)
        ]


def test_documents_carry_the_jsm_source(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = _documents(jsm_connector, _make_issue("HELP-1"))
    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_portal_metadata_is_added_when_available(
    jsm_connector: JiraServiceManagementConnector, mock_source_operations: MagicMock
) -> None:
    mock_source_operations.get_service_desk_request.return_value = {
        "requestType": {"name": "Report a system problem"},
        "currentStatus": {"status": "Waiting for support"},
    }
    mock_source_operations.get_service_desk_sla.return_value = {
        "values": [{"ongoingCycle": {"breached": True}}]
    }

    docs = _documents(jsm_connector, _make_issue("HELP-2"))

    assert docs[0].metadata["request_type"] == "Report a system problem"
    assert docs[0].metadata["portal_status"] == "Waiting for support"
    assert docs[0].metadata["sla_breached"] == "true"
    mock_source_operations.get_service_desk_request.assert_called_once_with(
        issue_key="HELP-2", fast=True
    )
    mock_source_operations.get_service_desk_sla.assert_called_once_with(
        issue_key="HELP-2", fast=True
    )


def test_enrichment_failure_still_indexes_the_ticket(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,  # noqa: ARG001
) -> None:
    """JSM not installed / no service desk access: gateway returns None and
    the ticket must index unchanged apart from the source stamp."""
    docs = _documents(jsm_connector, _make_issue("HELP-3"))

    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in docs[0].metadata
    assert "portal_status" not in docs[0].metadata
    assert "sla_breached" not in docs[0].metadata


def test_labels_to_skip_still_apply(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = _make_issue("HELP-4")
    issue["fields"]["labels"] = ["secret"]
    assert _documents(jsm_connector, issue) == []


def test_sla_breached_summary() -> None:
    assert (
        _sla_breached_summary({"values": [{"ongoingCycle": {"breached": False}}]})
        == "false"
    )
    assert (
        _sla_breached_summary(
            {
                "values": [
                    {"ongoingCycle": {"breached": False}},
                    {"completedCycles": [{"breached": True}]},
                ]
            }
        )
        == "true"
    )
    assert _sla_breached_summary({"values": []}) is None
    assert _sla_breached_summary({}) is None


def test_service_desk_url_is_not_under_the_versioned_jira_root() -> None:
    """Regression: the SDK's default base would resolve the Service Desk
    calls to ``{server}/rest/api/3/rest/servicedeskapi/...`` and 404."""
    url = _SERVICEDESK_BASE_URL.format(
        server="https://example.atlassian.net",
        rest_path="api",
        rest_api_version="3",
        path="request/IT-1",
    )
    assert url == "https://example.atlassian.net/rest/servicedeskapi/request/IT-1"
    assert "/rest/api/" not in url


def test_service_desk_ops_pass_the_servicedesk_base() -> None:
    """The gateway ops must call the SDK with the Service Desk base."""
    from onyx.connectors.jira.source_operations import JiraSourceOperations

    client = MagicMock()
    client._get_json.return_value = {"values": []}
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = None

    ops.get_service_desk_request(issue_key="IT-1")
    client._get_json.assert_called_with(
        "request/IT-1",
        params={"expand": "requestType"},
        base=_SERVICEDESK_BASE_URL,
    )

    ops.get_service_desk_sla(issue_key="IT-1")
    client._get_json.assert_called_with("request/IT-1/sla", base=_SERVICEDESK_BASE_URL)


def test_service_desk_ops_swallow_lookup_errors() -> None:
    """A raised _get_json error (JiraApiError / RequestException) must come
    back as None so enrichment never breaks an indexing run."""
    import requests

    from onyx.connectors.jira.source_operations import (
        JiraApiError,
        JiraSourceOperations,
    )

    for exc in (
        JiraApiError("boom", status_code=500),
        requests.RequestException("boom"),
    ):
        client = MagicMock()
        client._get_json.side_effect = exc
        ops = JiraSourceOperations.__new__(JiraSourceOperations)
        ops._cached_client = client
        ops._cached_fast_client = None

        assert ops.get_service_desk_request(issue_key="IT-1") is None
        assert ops.get_service_desk_sla(issue_key="IT-1") is None


def test_everything_scope_skips_non_service_desk_projects(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Default Everything scope: ordinary Jira issues must not index under
    the JSM source."""
    jsm_connector.jira_project = None  # Everything scope
    software_issue = _make_issue("ENG-1", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    assert _documents(jsm_connector, software_issue) == []
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_project_scope_indexes_non_service_desk_without_enrichment(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Explicit Project/JQL scope is the user's choice: the issue still
    indexes, but no portal lookups are made for a known software project."""
    jsm_connector.jira_project = "ENG"
    software_issue = _make_issue("ENG-2", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    docs = _documents(jsm_connector, software_issue)

    assert len(docs) == 1
    assert docs[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in docs[0].metadata
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_jql_scope_keeps_and_indexes_non_service_desk_issues(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """JQL-only configs also leave jira_project unset; their explicit query
    is the scope, so issues must not be dropped - only enrichment skips."""
    jsm_connector.jira_project = None
    jsm_connector.jql_query = "labels = portal"
    software_issue = _make_issue("ENG-3", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    docs = _documents(jsm_connector, software_issue)

    assert len(docs) == 1
    assert docs[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_everything_scope_filter_applies_to_slim_listing(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Pruning diffs slim IDs against the indexed set: the Everything-scope
    gate must hold there too, or moved issues keep stale JSM documents."""
    jsm_connector.jira_project = None
    jsm_connector.jql_query = None
    software_issue = _make_issue("ENG-4", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"
    desk_issue = _make_issue("HELP-6")

    assert jsm_connector._include_issue_in_slim_listing(software_issue) is False
    assert jsm_connector._include_issue_in_slim_listing(desk_issue) is True

    # explicit scopes are exempt, same as indexing
    jsm_connector.jql_query = "labels = portal"
    assert jsm_connector._include_issue_in_slim_listing(software_issue) is True
