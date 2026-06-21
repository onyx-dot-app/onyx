from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


def test_jira_service_management_requires_project_key() -> None:
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector(
            jira_base_url="https://jira.example.com",
            project_key="",
        )


def test_jira_service_management_uses_project_jql() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="HELP",
    )
    connector._jira_client = MagicMock()

    jql = connector._get_jql_query(start=0, end=60)

    assert 'project = "HELP"' in jql
    assert "updated >=" in jql


def test_jira_service_management_scopes_custom_jql_to_project() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="HELP",
        jql_query='status = "Open"',
    )
    connector._jira_client = MagicMock()

    jql = connector._get_jql_query(start=0, end=60)

    assert 'project = "HELP"' in jql
    assert 'status = "Open"' in jql
    assert "updated >=" in jql


def test_jira_service_management_sets_document_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="HELP",
    )

    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
