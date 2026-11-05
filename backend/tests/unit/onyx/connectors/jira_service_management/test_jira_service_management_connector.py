"""Unit tests for Jira Service Management connector."""

from typing import Any

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
