from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    credential_family_for_source,
    is_credential_usable_for_source,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.connectors.credential_family_base import CredentialFamily
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira_service_management.connector import (
    JSM_PROJECT_TYPE_JQL_FILTER,
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, HierarchyNode


@pytest.fixture
def jsm_base_url() -> str:
    return "https://acme.atlassian.net"


@pytest.fixture
def mock_jsm_source_operations() -> MagicMock:
    gateway = MagicMock(spec=JiraSourceOperations)
    gateway._is_cloud.return_value = True
    return gateway


def _build_jsm_connector(
    jsm_base_url: str,
    mock_jsm_source_operations: MagicMock,
    *,
    project_key: str | None = None,
    jql_query: str | None = None,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=jsm_base_url,
        project_key=project_key,
        jql_query=jql_query,
    )
    with patch(
        "onyx.connectors.jira.connector.JiraSourceOperations",
        return_value=mock_jsm_source_operations,
    ):
        connector.load_credentials(
            {
                "jira_user_email": "agent@acme.com",
                "jira_api_token": "secret-token",
            }
        )
    return connector


def test_factory_identifies_jsm_connector() -> None:
    connector_cls = identify_connector_class(DocumentSource.JIRA_SERVICE_MANAGEMENT)
    assert connector_cls is JiraServiceManagementConnector


def test_jsm_jql_query_default_all_service_desks(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(jsm_base_url, mock_jsm_source_operations)
    jql = connector._get_jql_query(start=100, end=200)
    assert jql == (
        f"{JSM_PROJECT_TYPE_JQL_FILTER} AND updated >= 100000 AND updated <= 200000"
    )


def test_jsm_jql_query_with_project_key(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, project_key="ITSM"
    )
    jql = connector._get_jql_query(start=100, end=200)
    assert jql == (
        f'project = "ITSM" AND {JSM_PROJECT_TYPE_JQL_FILTER} '
        "AND updated >= 100000 AND updated <= 200000"
    )


def test_jsm_jql_query_with_custom_jql_overrides_filter(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    custom = 'project = "ITSM" AND status = "Waiting for support"'
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, jql_query=custom
    )
    jql = connector._get_jql_query(start=100, end=200)
    assert jql == f"({custom}) AND updated >= 100000 AND updated <= 200000"


def test_jsm_search_issues_by_key_scopes_to_service_desk(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(jsm_base_url, mock_jsm_source_operations)
    mock_jsm_source_operations.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token=None
    )
    assert connector._search_issues_by_key(["ITSM-1", "ITSM-2"]) == []
    mock_jsm_source_operations.search_issue_ids.assert_called_once_with(
        jql=f'{JSM_PROJECT_TYPE_JQL_FILTER} AND key in ("ITSM-1", "ITSM-2")',
        next_page_token=None,
    )


def test_jsm_emits_documents_with_jsm_document_source(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, project_key="ITSM"
    )
    raw_issue: dict[str, Any] = {
        "id": "10001",
        "key": "ITSM-42",
        "fields": {
            "summary": "VPN connection failing",
            "description": "Cannot connect to corp VPN since morning update",
            "updated": "2026-10-27T10:00:00.000+0000",
            "created": "2026-10-27T09:00:00.000+0000",
            "project": {
                "id": "20001",
                "key": "ITSM",
                "name": "IT Service Desk",
                "projectTypeKey": "service_desk",
            },
            "issuetype": {"name": "Service Request"},
            "status": {"name": "Waiting for support"},
            "priority": {"name": "High"},
            "labels": ["vpn"],
            "comment": {"comments": []},
        },
    }
    items = list(connector._issue_to_items(raw_issue, seen_hierarchy_node_ids=set(), include_permissions=False))
    docs = [item for item in items if isinstance(item, Document)]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert len(docs) == 1
    assert len(nodes) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert docs[0].id == "https://acme.atlassian.net/browse/ITSM-42"
    assert docs[0].title == "ITSM-42 VPN connection failing"
    assert docs[0].semantic_identifier == "ITSM-42: VPN connection failing"


def test_jsm_validate_connector_settings_accepts_service_desk_project(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, project_key="ITSM"
    )
    mock_jsm_source_operations.get_project.return_value = {
        "key": "ITSM",
        "projectTypeKey": "service_desk",
    }
    connector.validate_connector_settings()
    mock_jsm_source_operations.get_project.assert_called_once_with(project_key="ITSM")


def test_jsm_validate_connector_settings_rejects_non_service_desk_project(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, project_key="ENG"
    )
    mock_jsm_source_operations.get_project.return_value = {
        "key": "ENG",
        "projectTypeKey": "software",
    }
    with pytest.raises(ConnectorValidationError, match="service_desk"):
        connector.validate_connector_settings()


def test_jsm_validate_connector_settings_handles_404(
    jsm_base_url: str, mock_jsm_source_operations: MagicMock
) -> None:
    connector = _build_jsm_connector(
        jsm_base_url, mock_jsm_source_operations, project_key="MISSING"
    )
    mock_jsm_source_operations.get_project.side_effect = JiraApiError(
        "Not found",
        status_code=404,
        body='{"errorMessages": ["No project could be found with key \'MISSING\'."]}',
    )
    with pytest.raises(ConnectorValidationError, match="No project could be found"):
        connector.validate_connector_settings()


def test_jsm_shares_atlassian_credential_family_with_jira() -> None:
    assert (
        credential_family_for_source(DocumentSource.JIRA_SERVICE_MANAGEMENT)
        == CredentialFamily.ATLASSIAN
    )
    stored = to_stored_credential_json(
        DocumentSource.JIRA,
        {
            "jira_user_email": "agent@acme.com",
            "jira_api_token": "secret-token",
        },
        None,
    )
    assert is_credential_usable_for_source(
        DocumentSource.JIRA, stored, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    assert to_source_credential_json(
        DocumentSource.JIRA_SERVICE_MANAGEMENT, stored
    ) == {
        "jira_user_email": "agent@acme.com",
        "jira_api_token": "secret-token",
    }
