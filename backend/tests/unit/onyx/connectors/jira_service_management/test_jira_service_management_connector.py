"""Unit tests for Jira Service Management connector."""

from typing import Any
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


def test_jsm_connector_initialization() -> None:
    """Test that JSM connector can be initialized with correct parameters."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="TEST",
    )

    assert connector.jira_base == "https://test.atlassian.net"
    assert connector.jira_project == "TEST"
    assert (
        connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    ), "JSM connector should have JIRA_SERVICE_MANAGEMENT as document source"


def test_jsm_connector_with_jql() -> None:
    """Test JSM connector initialization with JQL query."""
    jql_query = "project = 'SUPPORT' AND status = 'Open'"
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        jql_query=jql_query,
    )

    assert connector.jql_query == jql_query
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_connector_with_blacklist() -> None:
    """Test JSM connector with comment email blacklist."""
    blacklist = ["bot@example.com", "automation@example.com"]
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="SUPPORT",
        comment_email_blacklist=blacklist,
    )

    assert connector.comment_email_blacklist == tuple(blacklist)
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_comment_filtering_properties_as_dict() -> None:
    """Test JSM internal comment filtering with properties as dict."""
    # Public comment with properties as dict
    public_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Public comment",
                        "author": {"emailAddress": "user@example.com"},
                        "jsdPublic": True,
                        "properties": {
                            "sd.public.comment": {"internal": False}
                        },
                    }
                ]
            }
        }
    }
    
    # Internal comment with properties as dict
    internal_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Internal comment",
                        "author": {"emailAddress": "agent@example.com"},
                        "jsdPublic": False,
                        "properties": {
                            "sd.public.comment": {"internal": True}
                        },
                    }
                ]
            }
        }
    }
    
    # Test public comment is included
    public_comments = get_comment_strs(public_issue, skip_jsm_internal=True)
    assert len(public_comments) == 1
    assert public_comments[0] == "Public comment"
    
    # Test internal comment is excluded
    internal_comments = get_comment_strs(internal_issue, skip_jsm_internal=True)
    assert len(internal_comments) == 0


def test_jsm_comment_filtering_properties_as_list() -> None:
    """Test JSM internal comment filtering with properties as list."""
    # Public comment with properties as list
    public_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Public comment",
                        "author": {"emailAddress": "user@example.com"},
                        "properties": [
                            {
                                "key": "sd.public.comment",
                                "value": {"internal": False}
                            }
                        ],
                    }
                ]
            }
        }
    }
    
    # Internal comment with properties as list
    internal_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Internal comment",
                        "author": {"emailAddress": "agent@example.com"},
                        "properties": [
                            {
                                "key": "sd.public.comment",
                                "value": {"internal": True}
                            }
                        ],
                    }
                ]
            }
        }
    }
    
    # Test public comment is included
    public_comments = get_comment_strs(public_issue, skip_jsm_internal=True)
    assert len(public_comments) == 1
    assert public_comments[0] == "Public comment"
    
    # Test internal comment is excluded
    internal_comments = get_comment_strs(internal_issue, skip_jsm_internal=True)
    assert len(internal_comments) == 0


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_everything_scope_jql_cloud(mock_is_cloud: MagicMock) -> None:
    """Test that 'Everything' scope uses projectType filter on Cloud."""
    mock_is_cloud.return_value = True
    
    # Connector with no project_key and no jql_query (Everything scope)
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
    )
    
    # Mock source_operations
    connector._source_operations = MagicMock()
    
    # Get the JQL query for an arbitrary time range
    start = 1609459200  # 2021-01-01 00:00:00 UTC
    end = 1640995200    # 2022-01-01 00:00:00 UTC
    jql = connector._get_jql_query(start, end)
    
    # Verify that projectType filter is used on Cloud
    assert "projectType = service_desk" in jql, \
        "Cloud Everything scope should filter by projectType"
    assert "type = service_desk" not in jql, \
        "Should not use issue type filter (would fail)"
    assert "project IN" not in jql, \
        "Should not use project IN on Cloud"
    
    # Verify time range is still included
    assert "updated >=" in jql
    assert "updated <=" in jql


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_everything_scope_jql_dc_with_projects(mock_is_cloud: MagicMock) -> None:
    """Test that 'Everything' scope enumerates projects on Data Center."""
    mock_is_cloud.return_value = False
    
    # Connector with no project_key and no jql_query (Everything scope)
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    
    # Mock source_operations with JSM projects
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        {"key": "SUPPORT", "projectTypeKey": "service_desk"},
        {"key": "ITHELP", "projectTypeKey": "service_desk"},
        {"key": "PROJ", "projectTypeKey": "software"},
    ]
    connector._source_operations = mock_ops
    
    start = 1609459200
    end = 1640995200
    jql = connector._get_jql_query(start, end)
    
    # Verify that project IN filter is used on DC with quoted keys
    assert 'project IN ("SUPPORT", "ITHELP")' in jql, \
        "DC Everything scope should enumerate JSM projects with quoted keys"
    assert "projectType" not in jql, \
        "Should not use projectType on DC (field unavailable)"
    
    # Verify time range is still included
    assert "updated >=" in jql
    assert "updated <=" in jql


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_everything_scope_jql_dc_no_projects(mock_is_cloud: MagicMock) -> None:
    """Test that 'Everything' scope handles no JSM projects on Data Center."""
    mock_is_cloud.return_value = False
    
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    
    # Mock source_operations with no JSM projects
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        {"key": "PROJ", "projectTypeKey": "software"},
        {"key": "BUS", "projectTypeKey": "business"},
    ]
    connector._source_operations = mock_ops
    
    start = 1609459200
    end = 1640995200
    jql = connector._get_jql_query(start, end)
    
    # Verify that a valid no-match query is used when no JSM projects exist
    # 'id < 0' is syntactically valid JQL that matches nothing
    assert "id < 0" in jql, \
        "Should use valid no-match query when no JSM projects found"
    
    # Verify time range is still included
    assert "updated >=" in jql
    assert "updated <=" in jql


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_everything_scope_jql_dc_enumeration_failure(mock_is_cloud: MagicMock) -> None:
    """Test that project enumeration failures propagate as exceptions."""
    mock_is_cloud.return_value = False
    
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    
    # Mock source_operations to raise an exception
    mock_ops = MagicMock()
    mock_ops.list_projects.side_effect = Exception("API connection failed")
    connector._source_operations = mock_ops
    
    start = 1609459200
    end = 1640995200
    
    # Verify that the exception propagates (not caught and turned into empty list)
    try:
        connector._get_jql_query(start, end)
        assert False, "Expected exception to be raised"
    except Exception as e:
        assert "API connection failed" in str(e), \
            "Exception should propagate with original message"


def test_jsm_project_scope_no_projecttype_filter() -> None:
    """Test that specifying a project key doesn't add projectType filter."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="SUPPORT",
    )
    
    start = 1609459200
    end = 1640995200
    jql = connector._get_jql_query(start, end)
    
    # When project is specified, projectType filter should NOT be added
    assert "projectType" not in jql, \
        "projectType filter should only apply to Everything scope"
    assert 'project = "SUPPORT"' in jql or "project = SUPPORT" in jql
    

def test_jsm_custom_jql_no_projecttype_filter() -> None:
    """Test that custom JQL doesn't add projectType filter."""
    custom_jql = "project = 'SUPPORT' AND status = 'Open'"
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        jql_query=custom_jql,
    )
    
    start = 1609459200
    end = 1640995200
    jql = connector._get_jql_query(start, end)
    
    # When custom JQL is provided, projectType filter should NOT be added
    assert "projectType" not in jql, \
        "projectType filter should only apply to Everything scope"
    # Custom JQL should be preserved
    assert custom_jql in jql


def test_jsm_comment_filtering_string_markers() -> None:
    """Test JSM internal comment filtering with string-valued boolean markers."""
    # Comment with string "true" for jsdPublic
    public_string_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Public string comment",
                        "author": {"emailAddress": "user@example.com"},
                        "jsdPublic": "true",
                    }
                ]
            }
        }
    }
    
    # Comment with string "false" for jsdPublic
    internal_string_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Internal string comment",
                        "author": {"emailAddress": "agent@example.com"},
                        "jsdPublic": "false",
                    }
                ]
            }
        }
    }
    
    # Comment with string "true" for internal property
    internal_property_string_issue: dict[str, Any] = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "body": "Internal property string comment",
                        "author": {"emailAddress": "agent@example.com"},
                        "properties": {
                            "sd.public.comment": {"internal": "true"}
                        },
                    }
                ]
            }
        }
    }
    
    # Test string "true" for jsdPublic is treated as public
    public_comments = get_comment_strs(public_string_issue, skip_jsm_internal=True)
    assert len(public_comments) == 1
    assert public_comments[0] == "Public string comment"
    
    # Test string "false" for jsdPublic is treated as internal
    internal_comments = get_comment_strs(internal_string_issue, skip_jsm_internal=True)
    assert len(internal_comments) == 0
    
    # Test string "true" for internal property is treated as internal
    internal_property_comments = get_comment_strs(
        internal_property_string_issue, skip_jsm_internal=True
    )
    assert len(internal_property_comments) == 0


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_search_by_key_everything_scope_cloud(mock_is_cloud: MagicMock) -> None:
    """Test that _search_issues_by_key applies JSM scope for Everything on Cloud."""
    mock_is_cloud.return_value = True
    
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
    )
    
    mock_ops = MagicMock()
    connector._source_operations = mock_ops
    
    # Mock _search_all_issues to capture the JQL
    captured_jql: list[str] = []
    def capture_jql(jql: str) -> list[dict[str, Any]]:
        captured_jql.append(jql)
        return []
    
    connector._search_all_issues = capture_jql  # type: ignore[method-assign]
    
    # Call _search_issues_by_key with test keys
    connector._search_issues_by_key(["TEST-1", "TEST-2"])
    
    # Verify JSM scope was applied
    assert len(captured_jql) == 1
    jql = captured_jql[0]
    assert "projectType = service_desk" in jql, \
        "Everything scope should apply JSM filter in retry/reindex"
    assert 'key in ("TEST-1", "TEST-2")' in jql, \
        "Should include the key clause"


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_search_by_key_everything_scope_dc(mock_is_cloud: MagicMock) -> None:
    """Test that _search_issues_by_key applies JSM scope for Everything on DC."""
    mock_is_cloud.return_value = False
    
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        {"key": "SUPPORT", "projectTypeKey": "service_desk"},
        {"key": "ITHELP", "projectTypeKey": "service_desk"},
    ]
    connector._source_operations = mock_ops
    
    captured_jql: list[str] = []
    def capture_jql(jql: str) -> list[dict[str, Any]]:
        captured_jql.append(jql)
        return []
    
    connector._search_all_issues = capture_jql  # type: ignore[method-assign]
    
    connector._search_issues_by_key(["TEST-1", "TEST-2"])
    
    assert len(captured_jql) == 1
    jql = captured_jql[0]
    assert 'project IN ("SUPPORT", "ITHELP")' in jql, \
        "DC Everything scope should enumerate JSM projects with quoted keys in retry/reindex"
    assert 'key in ("TEST-1", "TEST-2")' in jql


def test_jsm_search_by_key_project_scoped() -> None:
    """Test that _search_issues_by_key does not add JSM filter when project is set."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="SUPPORT",
    )
    
    mock_ops = MagicMock()
    connector._source_operations = mock_ops
    
    captured_jql: list[str] = []
    def capture_jql(jql: str) -> list[dict[str, Any]]:
        captured_jql.append(jql)
        return []
    
    connector._search_all_issues = capture_jql  # type: ignore[method-assign]
    
    connector._search_issues_by_key(["TEST-1"])
    
    assert len(captured_jql) == 1
    jql = captured_jql[0]
    assert "projectType" not in jql, \
        "Should not add JSM filter when project is explicitly set"
    assert "project IN" not in jql, \
        "Should not enumerate projects when project key is set"
    assert 'project = "SUPPORT"' in jql


def test_jsm_search_by_key_jql_scoped() -> None:
    """Test that _search_issues_by_key does not add JSM filter when JQL is set."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        jql_query="project = SUPPORT AND status = Open",
    )
    
    mock_ops = MagicMock()
    connector._source_operations = mock_ops
    
    captured_jql: list[str] = []
    def capture_jql(jql: str) -> list[dict[str, Any]]:
        captured_jql.append(jql)
        return []
    
    connector._search_all_issues = capture_jql  # type: ignore[method-assign]
    
    connector._search_issues_by_key(["TEST-1"])
    
    assert len(captured_jql) == 1
    jql = captured_jql[0]
    assert "projectType" not in jql, \
        "Should not add JSM filter when custom JQL is set"
    assert "project = SUPPORT AND status = Open" in jql, \
        "Should use custom JQL when provided"


@patch("onyx.connectors.jira_service_management.connector.is_cloud_gateway")
def test_jsm_project_list_cached_dc(mock_is_cloud: MagicMock) -> None:
    """Test that Data Center project list is cached and not called repeatedly."""
    mock_is_cloud.return_value = False
    
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )
    
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        {"key": "SUPPORT", "projectTypeKey": "service_desk"},
        {"key": "ITHELP", "projectTypeKey": "service_desk"},
    ]
    connector._source_operations = mock_ops
    
    captured_jql: list[str] = []
    def capture_jql(jql: str) -> list[dict[str, Any]]:
        captured_jql.append(jql)
        return []
    
    connector._search_all_issues = capture_jql  # type: ignore[method-assign]
    
    # First call should fetch projects
    connector._search_issues_by_key(["TEST-1"])
    assert mock_ops.list_projects.call_count == 1, \
        "First call should fetch project list"
    
    # Second call should reuse cache
    connector._search_issues_by_key(["TEST-2", "TEST-3"])
    assert mock_ops.list_projects.call_count == 1, \
        "Second call should reuse cached project list"
    
    # Third call with _get_jql_query should also reuse cache
    connector._get_jql_query(start=1609459200, end=1640995200)
    assert mock_ops.list_projects.call_count == 1, \
        "Subsequent _get_jql_query call should reuse cached project list"
    
    # All JQL queries should have the same project filter
    assert len(captured_jql) == 2
    for jql in captured_jql:
        assert 'project IN ("SUPPORT", "ITHELP")' in jql
