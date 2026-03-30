"""Tests for the Jira Service Management connector.

These tests verify:
- Correct inheritance from JiraConnector
- Dynamic JSM field discovery with caching
- JSM metadata enrichment and SLA extraction
- JQL query generation with JSM issue type filters
- Graceful handling of missing/broken JSM fields
"""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.connector import _extract_request_type_name
from onyx.connectors.jira_service_management.connector import _extract_sla_display
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection

# Patch targets for base class (hook pattern — JSM no longer overrides _load_from_checkpoint)
_PATCH_JQL_SEARCH = "onyx.connectors.jira.connector._perform_jql_search"
_PATCH_PROCESS_ISSUE = "onyx.connectors.jira.connector.process_jira_issue"


def _make_connector(
    service_desk_id: str | None = None,
    project_key: str | None = None,
    jql_query: str | None = None,
) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        service_desk_id=service_desk_id,
        project_key=project_key,
        jql_query=jql_query,
    )


def _make_mock_issue(
    key: str = "SD-1",
    summary: str = "Test ticket",
    description: str = "Test description",
    issuetype_name: str = "Service Request",
    extra_fields: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock Jira Issue with the given fields."""
    issue = MagicMock(spec=Issue)
    issue.key = key

    fields = MagicMock()
    fields.summary = summary
    fields.description = description
    fields.comment = MagicMock()
    fields.comment.comments = []
    fields.labels = []
    fields.updated = "2025-03-26T10:00:00.000+0000"

    issuetype = MagicMock()
    issuetype.name = issuetype_name
    fields.issuetype = issuetype

    fields.reporter = None
    fields.assignee = None
    fields.priority = None
    fields.status = None
    fields.resolution = None
    fields.created = None
    fields.duedate = None
    fields.parent = None
    fields.project = None
    fields.resolutiondate = None

    issue.fields = fields

    raw_fields: dict[str, Any] = {
        "description": description,
        "summary": summary,
        "issuetype": {"name": issuetype_name},
        "labels": [],
        "comment": {"comments": []},
        "updated": "2025-03-26T10:00:00.000+0000",
    }
    if extra_fields:
        raw_fields.update(extra_fields)
    issue.raw = {"fields": raw_fields}

    return issue


def _make_mock_document(
    doc_id: str = "https://example.atlassian.net/browse/SD-1",
) -> Document:
    return Document(
        id=doc_id,
        sections=[TextSection(link=doc_id, text="Test content")],
        source=DocumentSource.JIRA,
        semantic_identifier="SD-1: Test ticket",
        title="SD-1 Test ticket",
        metadata={"key": "SD-1", "issuetype": "Service Request"},
    )


class TestJSMConnectorInitialization:
    def test_connector_initialization(self) -> None:
        connector = _make_connector(service_desk_id="5", project_key="SD")
        assert connector.service_desk_id == "5"
        assert connector.jira_project == "SD"
        assert connector._jsm_field_map is None

    def test_inherits_jira_connector(self) -> None:
        connector = _make_connector()
        assert isinstance(connector, JiraConnector)

    def test_service_desk_id_stored(self) -> None:
        connector = _make_connector(service_desk_id="42")
        assert connector.service_desk_id == "42"

    def test_service_desk_id_optional(self) -> None:
        connector = _make_connector()
        assert connector.service_desk_id is None

    def test_credential_loading(self) -> None:
        connector = _make_connector()
        connector.load_credentials(
            {
                "jira_user_email": "test@example.com",
                "jira_api_token": "test-token",
            }
        )
        assert connector._jira_client is not None

    def test_document_source_enum_exists(self) -> None:
        assert hasattr(DocumentSource, "JIRA_SERVICE_MANAGEMENT")
        assert DocumentSource.JIRA_SERVICE_MANAGEMENT == "jira_service_management"


class TestDynamicFieldDiscovery:
    def test_dynamic_field_discovery_success(self) -> None:
        connector = _make_connector()
        mock_client = MagicMock()
        mock_client.fields.return_value = [
            {"name": "Customer Request Type", "id": "customfield_10010", "custom": True},
            {"name": "Time to first response", "id": "customfield_10020", "custom": True},
            {"name": "Time to resolution", "id": "customfield_10030", "custom": True},
            {"name": "Summary", "id": "summary", "custom": False},
        ]
        connector._jira_client = mock_client

        field_map = connector._discover_jsm_fields()
        assert field_map["request_type"] == "customfield_10010"
        assert field_map["time_to_first_response"] == "customfield_10020"
        assert field_map["time_to_resolution"] == "customfield_10030"

    def test_dynamic_field_discovery_failure_graceful(self) -> None:
        connector = _make_connector()
        mock_client = MagicMock()
        mock_client.fields.side_effect = Exception("API error")
        connector._jira_client = mock_client

        field_map = connector._discover_jsm_fields()
        assert field_map == {}

    def test_dynamic_field_discovery_cached(self) -> None:
        connector = _make_connector()
        mock_client = MagicMock()
        mock_client.fields.return_value = [
            {"name": "Customer Request Type", "id": "customfield_10010", "custom": True},
        ]
        connector._jira_client = mock_client

        # First call
        field_map_1 = connector._discover_jsm_fields()
        # Second call should use cache
        field_map_2 = connector._discover_jsm_fields()

        assert field_map_1 == field_map_2
        # fields() should only be called once
        assert mock_client.fields.call_count == 1

    def test_discovery_partial_fields(self) -> None:
        """Only some JSM fields may exist on an instance."""
        connector = _make_connector()
        mock_client = MagicMock()
        mock_client.fields.return_value = [
            {"name": "Request Type", "id": "customfield_99", "custom": True},
        ]
        connector._jira_client = mock_client

        field_map = connector._discover_jsm_fields()
        assert "request_type" in field_map
        assert "time_to_first_response" not in field_map
        assert "time_to_resolution" not in field_map


class TestJSMMetadataEnrichment:
    def test_jsm_metadata_enrichment(self) -> None:
        connector = _make_connector()
        connector._jsm_field_map = {
            "request_type": "customfield_10010",
        }

        issue = _make_mock_issue(
            extra_fields={"customfield_10010": {"requestType": {"name": "Hardware Request"}}}
        )
        doc = _make_mock_document()

        enriched = connector._enrich_document_with_jsm_metadata(doc, issue)
        assert enriched.metadata.get("request_type") == "Hardware Request"
        assert enriched.source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_sla_extraction_complete(self) -> None:
        connector = _make_connector()
        connector._jsm_field_map = {
            "time_to_first_response": "customfield_10020",
            "time_to_resolution": "customfield_10030",
        }

        issue = _make_mock_issue(
            extra_fields={
                "customfield_10020": {
                    "ongoingCycle": {
                        "breached": False,
                        "remainingTime": {"friendly": "2h 30m"},
                    }
                },
                "customfield_10030": {
                    "ongoingCycle": {
                        "breached": True,
                        "remainingTime": {"friendly": "-1h 15m"},
                    }
                },
            }
        )
        doc = _make_mock_document()

        enriched = connector._enrich_document_with_jsm_metadata(doc, issue)
        assert enriched.metadata.get("time_to_first_response") == "2h 30m"
        assert enriched.metadata.get("time_to_resolution") == "-1h 15m"
        assert enriched.metadata.get("sla_breached") == "true"

    def test_sla_extraction_missing_fields_graceful(self) -> None:
        connector = _make_connector()
        connector._jsm_field_map = {
            "time_to_first_response": "customfield_10020",
            "time_to_resolution": "customfield_10030",
        }

        # Issue has no SLA fields
        issue = _make_mock_issue()
        doc = _make_mock_document()

        enriched = connector._enrich_document_with_jsm_metadata(doc, issue)
        assert "time_to_first_response" not in enriched.metadata
        assert "time_to_resolution" not in enriched.metadata
        assert "sla_breached" not in enriched.metadata

    def test_source_overridden_to_jsm(self) -> None:
        connector = _make_connector()
        connector._jsm_field_map = {}

        issue = _make_mock_issue()
        doc = _make_mock_document()
        assert doc.source == DocumentSource.JIRA

        enriched = connector._enrich_document_with_jsm_metadata(doc, issue)
        assert enriched.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


class TestJQLGeneration:
    def test_jql_includes_jsm_issue_types(self) -> None:
        connector = _make_connector()
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert "issuetype in" in jql
        assert '"Service Request"' in jql
        assert '"Incident"' in jql
        assert '"Problem"' in jql
        assert '"Change"' in jql

    def test_jql_with_project_key(self) -> None:
        connector = _make_connector(project_key="SD")
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert 'project = "SD"' in jql
        assert "issuetype in" in jql

    def test_jql_custom_query_no_jsm_filter(self) -> None:
        """When user provides custom JQL without service_desk_id, trust the user."""
        connector = _make_connector(jql_query="project = SD AND priority = High")
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert "project = SD AND priority = High" in jql
        assert "issuetype in" not in jql

    def test_jql_custom_query_with_service_desk_id_still_filters(self) -> None:
        """When service_desk_id is set, JSM issue type filter is always applied."""
        connector = _make_connector(
            service_desk_id="5",
            jql_query="priority = High",
        )
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert "priority = High" in jql
        assert "issuetype in" in jql

    def test_jql_service_desk_id_no_project_scopes_to_service_desk(self) -> None:
        """service_desk_id without project_key must scope query to that project."""
        connector = _make_connector(service_desk_id="SD-HELPDESK")
        jql = connector._get_jql_query(0.0, 9999999999.0)
        # Must include both a project scope AND the JSM issue-type filter
        assert "project = SD-HELPDESK" in jql
        assert "issuetype in" in jql

    def test_jql_service_desk_id_with_project_key_no_duplicate_project(self) -> None:
        """When both service_desk_id and project_key are set, project scoping
        comes from project_key (via base class) and service_desk_id is not
        added a second time."""
        connector = _make_connector(service_desk_id="SD-HELPDESK", project_key="SD")
        jql = connector._get_jql_query(0.0, 9999999999.0)
        # project_key drives the project clause; service_desk_id must NOT be
        # injected again to avoid a duplicate / conflicting project filter.
        assert 'project = "SD"' in jql
        assert "project = SD-HELPDESK" not in jql
        assert "issuetype in" in jql

    def test_jql_service_desk_id_with_custom_jql_no_project_injection(self) -> None:
        """When service_desk_id and custom jql_query are both set, the project
        scope is NOT injected (the caller's JQL is trusted to scope correctly)."""
        connector = _make_connector(
            service_desk_id="SD-HELPDESK",
            jql_query="project = SD-HELPDESK AND priority = High",
        )
        jql = connector._get_jql_query(0.0, 9999999999.0)
        # Custom JQL is preserved; no duplicate project clause injected
        assert "project = SD-HELPDESK AND priority = High" in jql
        assert jql.count("project = SD-HELPDESK") == 1


class TestSLAHelpers:
    def test_extract_sla_display_ongoing_cycle(self) -> None:
        sla = {
            "ongoingCycle": {
                "breached": False,
                "remainingTime": {"friendly": "4h"},
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display == "4h"
        assert breached is False

    def test_extract_sla_display_breached(self) -> None:
        sla = {
            "ongoingCycle": {
                "breached": True,
                "remainingTime": {"friendly": "-2h"},
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display == "-2h"
        assert breached is True

    def test_extract_sla_display_completed_cycle(self) -> None:
        sla = {
            "completedCycles": [
                {
                    "breached": False,
                    "elapsedTime": {"friendly": "1h 20m"},
                }
            ]
        }
        display, breached = _extract_sla_display(sla)
        assert display == "1h 20m"
        assert breached is False

    def test_extract_sla_display_string(self) -> None:
        display, breached = _extract_sla_display("3h remaining")
        assert display == "3h remaining"
        assert breached is False

    def test_extract_sla_display_none(self) -> None:
        display, breached = _extract_sla_display(None)
        assert display is None
        assert breached is False

    def test_extract_sla_display_breached_no_friendly(self) -> None:
        """Breached=True but no friendly string should return 'Breached' fallback."""
        sla = {
            "ongoingCycle": {
                "breached": True,
                "remainingTime": {},
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display == "Breached"
        assert breached is True

    def test_extract_sla_display_breached_no_remaining_time(self) -> None:
        """Breached=True with no remainingTime key at all."""
        sla = {
            "ongoingCycle": {
                "breached": True,
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display == "Breached"
        assert breached is True

    def test_extract_sla_display_completed_breached_no_elapsed(self) -> None:
        """Completed cycle breached but no elapsed time display."""
        sla = {
            "completedCycles": [
                {
                    "breached": True,
                    "elapsedTime": {},
                }
            ]
        }
        display, breached = _extract_sla_display(sla)
        assert display == "Breached"
        assert breached is True

    def test_extract_request_type_name_dict(self) -> None:
        rt = {"requestType": {"name": "VPN Access"}}
        assert _extract_request_type_name(rt) == "VPN Access"

    def test_extract_request_type_name_string(self) -> None:
        assert _extract_request_type_name("Hardware Request") == "Hardware Request"

    def test_extract_request_type_name_none(self) -> None:
        assert _extract_request_type_name(None) is None


class TestLoadFromCheckpointEnrichment:
    """Verify that _load_from_checkpoint calls JSM enrichment via hook pattern."""

    @patch(_PATCH_JQL_SEARCH)
    @patch(_PATCH_PROCESS_ISSUE)
    def test_load_from_checkpoint_enriches_documents(
        self,
        mock_process_jira_issue: MagicMock,
        mock_jql_search: MagicMock,
    ) -> None:
        connector = _make_connector()
        connector._jsm_field_map = {}

        issue = _make_mock_issue()
        mock_jql_search.return_value = iter([issue])

        base_doc = _make_mock_document()
        base_doc.source = DocumentSource.JIRA
        mock_process_jira_issue.return_value = base_doc

        checkpoint = JiraConnectorCheckpoint(
            has_more=True,
            offset=0,
            cursor=None,
            all_issue_ids=[],
            ids_done=True,
            seen_hierarchy_node_ids=[],
        )

        results = list(
            connector._load_from_checkpoint(
                jql="issuetype in (\"Service Request\")",
                checkpoint=checkpoint,
                include_permissions=False,
            )
        )

        # Should have yielded the enriched document via hook pattern
        docs = [r for r in results if isinstance(r, Document)]
        assert len(docs) == 1
        assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_enrich_document_hook_delegates_to_jsm_metadata(self) -> None:
        """Verify _enrich_document calls _enrich_document_with_jsm_metadata."""
        connector = _make_connector()
        connector._jsm_field_map = {}

        issue = _make_mock_issue()
        doc = _make_mock_document()
        assert doc.source == DocumentSource.JIRA

        enriched = connector._enrich_document(doc, issue)
        assert enriched.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
