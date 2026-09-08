"""Unit tests for the Jira Service Management connector.

These tests exercise the logic that is specific to JSM (source stamping,
service-desk project discovery, and JQL scoping) with a mocked Jira client, so
they run in CI without a live Jira instance or credentials.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)

BASE_URL = "https://danswerai.atlassian.net"

# Fixed window so the epoch-ms bounds in the asserted JQL are deterministic.
START = 1_000_000.0
END = 2_000_000.0
TIME_JQL = "updated >= 1000000000 AND updated <= 2000000000"


def _project(key: str, project_type: str) -> SimpleNamespace:
    return SimpleNamespace(key=key, projectTypeKey=project_type)


def _connector(**kwargs: object) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(jira_base_url=BASE_URL, **kwargs)


def test_document_source_is_jira_service_management() -> None:
    connector = _connector()
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_service_desk_project_keys_filters_by_type_and_caches() -> None:
    connector = _connector()
    mock_client = MagicMock()
    mock_client.projects.return_value = [
        _project("SUP", "service_desk"),
        _project("ENG", "software"),
        _project("OPS", "service_desk"),
        _project("BIZ", "business"),
    ]
    connector._jira_client = mock_client

    keys = connector._get_service_desk_project_keys()
    assert keys == ["SUP", "OPS"]

    # Second call should hit the cache, not re-list projects.
    keys_again = connector._get_service_desk_project_keys()
    assert keys_again == ["SUP", "OPS"]
    mock_client.projects.assert_called_once()


def test_jql_uses_custom_query_verbatim() -> None:
    connector = _connector(jql_query="project = 'SUP' AND issuetype = Incident")
    jql = connector._get_jql_query(START, END)
    assert jql == f"(project = 'SUP' AND issuetype = Incident) AND {TIME_JQL}"


def test_jql_scopes_to_explicit_project_key() -> None:
    connector = _connector(project_key="SUP")
    jql = connector._get_jql_query(START, END)
    assert jql == f'project = "SUP" AND {TIME_JQL}'


def test_jql_auto_scopes_to_service_desk_projects() -> None:
    connector = _connector()
    mock_client = MagicMock()
    mock_client.projects.return_value = [
        _project("SUP", "service_desk"),
        _project("ENG", "software"),
        _project("OPS", "service_desk"),
    ]
    connector._jira_client = mock_client

    jql = connector._get_jql_query(START, END)
    assert jql == f'project in ("SUP", "OPS") AND {TIME_JQL}'


def test_jql_raises_when_no_service_desk_projects() -> None:
    connector = _connector()
    mock_client = MagicMock()
    mock_client.projects.return_value = [
        _project("ENG", "software"),
        _project("BIZ", "business"),
    ]
    connector._jira_client = mock_client

    with pytest.raises(ConnectorValidationError):
        connector._get_jql_query(START, END)


def test_projects_without_type_key_are_ignored() -> None:
    connector = _connector()
    mock_client = MagicMock()
    # A project resource missing projectTypeKey must not crash discovery.
    mock_client.projects.return_value = [
        SimpleNamespace(key="LEGACY"),
        _project("SUP", "service_desk"),
    ]
    connector._jira_client = mock_client

    assert connector._get_service_desk_project_keys() == ["SUP"]
