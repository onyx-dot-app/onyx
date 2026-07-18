"""Unit tests for the Jira Service Management connector."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jsm.connector import JsmConnector, _JSM_JQL_TYPE_FILTER
from onyx.connectors.models import Document, TextSection


def _make_doc(key: str = "IT-1") -> Document:
    return Document(
        id=f"https://example.atlassian.net/browse/{key}",
        sections=[TextSection(link=f"https://example.atlassian.net/browse/{key}", text="Test")],
        source=DocumentSource.JIRA,
        semantic_identifier=f"{key}: Test issue",
        metadata={"key": key, "status": "Open"},
    )


class TestJsmConnectorInit:
    def test_default_init(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        assert connector.jira_base == "https://example.atlassian.net"
        assert connector.jira_project is None
        assert connector._user_supplied_jql is False

    def test_init_with_project(self) -> None:
        connector = JsmConnector(
            jira_base_url="https://example.atlassian.net",
            project_key="IT",
        )
        assert connector.jira_project == "IT"

    def test_init_with_custom_jql(self) -> None:
        connector = JsmConnector(
            jira_base_url="https://example.atlassian.net",
            jql_query="project = IT AND priority = High",
        )
        assert connector._user_supplied_jql is True


class TestJsmJqlQuery:
    def test_default_jql_includes_jsm_type_filter(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert _JSM_JQL_TYPE_FILTER in jql

    def test_project_jql_scoped_to_jsm_types(self) -> None:
        connector = JsmConnector(
            jira_base_url="https://example.atlassian.net",
            project_key="IT",
        )
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert 'project = "IT"' in jql
        assert _JSM_JQL_TYPE_FILTER in jql

    def test_custom_jql_passes_through_without_type_filter(self) -> None:
        custom_jql = "project = IT AND priority = High"
        connector = JsmConnector(
            jira_base_url="https://example.atlassian.net",
            jql_query=custom_jql,
        )
        jql = connector._get_jql_query(0.0, 9999999999.0)
        assert custom_jql in jql
        assert "issuetype in" not in jql


class TestDocumentEnrichment:
    def test_source_is_jsm(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        connector._jira_client = None  # skip API call
        doc = _make_doc()
        enriched = connector._enrich_document(doc)
        assert enriched.source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_legacy_field_rename(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        connector._jira_client = None
        doc = _make_doc()
        doc.metadata["request-type"] = "IT Help"
        doc.metadata["customer-satisfaction"] = "5"
        enriched = connector._enrich_document(doc)
        assert "jsm_request_type" in enriched.metadata
        assert enriched.metadata["jsm_request_type"] == "IT Help"
        assert "request-type" not in enriched.metadata
        assert "jsm_satisfaction_score" in enriched.metadata
        assert "customer-satisfaction" not in enriched.metadata

    def test_fetch_jsm_metadata_graceful_on_non_200(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        mock_client = MagicMock()
        mock_client._options = {"server": "https://example.atlassian.net"}
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_client._session.get.return_value = mock_resp
        connector._jira_client = mock_client
        result = connector._fetch_jsm_request_metadata("IT-1")
        assert result == {}

    def test_fetch_jsm_metadata_parses_response(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        mock_client = MagicMock()
        mock_client._options = {"server": "https://example.atlassian.net"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "requestType": {"name": "Get IT help", "id": "1"},
            "currentStatus": {"status": "Waiting for support", "statusCategory": "NEW"},
            "reporter": {
                "displayName": "Alice Smith",
                "emailAddress": "alice@example.com",
            },
            "sla": {"values": []},
        }
        mock_client._session.get.return_value = mock_resp
        connector._jira_client = mock_client

        meta = connector._fetch_jsm_request_metadata("IT-1")
        assert meta["jsm_request_type"] == "Get IT help"
        assert meta["jsm_status"] == "Waiting for support"
        assert meta["jsm_customer"] == "Alice Smith"
        assert meta["jsm_customer_email"] == "alice@example.com"

    def test_fetch_jsm_metadata_detects_sla_breach(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        mock_client = MagicMock()
        mock_client._options = {"server": "https://example.atlassian.net"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sla": {
                "values": [
                    {
                        "name": "Time to first response",
                        "completedCycles": [{"breached": True}],
                    }
                ]
            }
        }
        mock_client._session.get.return_value = mock_resp
        connector._jira_client = mock_client

        meta = connector._fetch_jsm_request_metadata("IT-1")
        assert "jsm_sla_breached" in meta
        assert "Time to first response" in meta["jsm_sla_breached"]

    def test_fetch_jsm_metadata_graceful_on_exception(self) -> None:
        connector = JsmConnector(jira_base_url="https://example.atlassian.net")
        mock_client = MagicMock()
        mock_client._options = {"server": "https://example.atlassian.net"}
        mock_client._session.get.side_effect = Exception("network error")
        connector._jira_client = mock_client
        result = connector._fetch_jsm_request_metadata("IT-1")
        assert result == {}
