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
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _sla_breached_summary,
)
from onyx.connectors.models import Document


def _make_issue(key: str, project_key: str = "HELP") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "project": {"key": project_key, "name": "Help Desk"},
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
        issue_key="HELP-2"
    )
    mock_source_operations.get_service_desk_sla.assert_called_once_with(
        issue_key="HELP-2"
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
