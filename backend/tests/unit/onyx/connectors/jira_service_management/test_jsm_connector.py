from unittest.mock import MagicMock
from jira.resources import Issue
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import process_jsm_issue
from onyx.connectors.models import Document

def test_process_jsm_issue_with_request_type():
    """Test that process_jsm_issue correctly extracts JSM request type metadata"""
    mock_issue = MagicMock(spec=Issue)
    mock_issue.key = "SD-123"
    mock_issue.fields = MagicMock()
    mock_issue.fields.summary = "Hardware Problem"
    mock_issue.fields.description = "My laptop is broken"
    mock_issue.fields.updated = "2023-10-27T10:00:00.000+0000"
    mock_issue.fields.labels = []
    mock_issue.fields.comment.comments = []
    
    # Standard Jira fields
    mock_issue.fields.reporter.displayName = "John Doe"
    mock_issue.fields.reporter.emailAddress = "john@example.com"
    mock_issue.fields.assignee = None
    mock_issue.fields.priority.name = "High"
    mock_issue.fields.status.name = "Open"
    mock_issue.fields.issuetype.name = "Incident"
    mock_issue.fields.project.key = "SD"
    mock_issue.fields.project.name = "Service Desk"
    mock_issue.fields.parent = None
    mock_issue.fields.resolution = None
    
    # Mock the JSM-specific Request Type field (customfield_10010)
    mock_issue.raw = {
        "fields": {
            "description": "My laptop is broken",
            "customfield_10010": {"requestType": {"name": "Get IT Help"}}
        }
    }

    doc = process_jsm_issue(
        jira_base_url="https://example.atlassian.net",
        issue=mock_issue
    )

    assert isinstance(doc, Document)
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.metadata["request_type"] == "Get IT Help"
    assert doc.metadata["project"] == "SD"
    assert "Incident" in doc.metadata["issuetype"]

def test_process_jsm_issue_no_request_type():
    """Test processing a JSM issue that doesn't have a request type field"""
    mock_issue = MagicMock(spec=Issue)
    mock_issue.key = "SD-124"
    mock_issue.fields = MagicMock()
    mock_issue.fields.summary = "General Question"
    mock_issue.fields.description = "How do I use this?"
    mock_issue.fields.updated = "2023-10-27T11:00:00.000+0000"
    mock_issue.fields.labels = []
    mock_issue.fields.comment.comments = []
    
    mock_issue.fields.reporter.displayName = "Jane Doe"
    mock_issue.fields.reporter.emailAddress = "jane@example.com"
    mock_issue.fields.assignee = None
    mock_issue.fields.priority.name = "Medium"
    mock_issue.fields.status.name = "Closed"
    mock_issue.fields.issuetype.name = "Service Request"
    mock_issue.fields.project.key = "SD"
    mock_issue.fields.project.name = "Service Desk"
    mock_issue.fields.parent = None
    mock_issue.fields.resolution = None
    
    # No JSM field in raw
    mock_issue.raw = {
        "fields": {
            "description": "How do I use this?"
        }
    }

    doc = process_jsm_issue(
        jira_base_url="https://example.atlassian.net",
        issue=mock_issue
    )

    assert isinstance(doc, Document)
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in doc.metadata
    assert doc.metadata["project"] == "SD"
