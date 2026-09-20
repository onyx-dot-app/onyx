from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.jira.utils import (
    JIRA_CLOUD_API_VERSION,
    JIRA_SERVER_API_VERSION,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def jira_base_url() -> str:
    return "https://jira.example.com"


@pytest.fixture
def project_key() -> str:
    return "IT"


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    mock.project = MagicMock()
    mock.projects = MagicMock()
    mock.fields = MagicMock(
        return_value=[
            {"id": "customfield_10010", "name": "Customer Request Type"},
            {"id": "customfield_10002", "name": "Organizations"},
            {"id": "customfield_10003", "name": "Request participants"},
            {"id": "customfield_10999", "name": "Time to resolution"},
        ]
    )
    mock._options = {"rest_api_version": JIRA_SERVER_API_VERSION}
    mock._session = MagicMock()
    return mock


@pytest.fixture
def mock_jira_client_cloud(mock_jira_client: MagicMock) -> MagicMock:
    """Mock client for the Cloud (v3) path: enhanced_search_ids via
    session.get(search/jql) and bulk_fetch_issues via session.post
    (issue/bulkfetch)."""
    mock_jira_client._options["rest_api_version"] = JIRA_CLOUD_API_VERSION
    mock_jira_client._get_url = MagicMock(
        side_effect=lambda path: f"https://jira.example.com/rest/api/3/{path}"
    )
    return mock_jira_client


@pytest.fixture
def jsm_connector(
    jira_base_url: str, project_key: str, mock_jira_client: MagicMock
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        comment_email_blacklist=["blacklist@example.com"],
        labels_to_skip=["secret", "sensitive"],
        include_attachments=True,
    )
    connector._jira_client = mock_jira_client
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_jsm_issue() -> Any:
    def _create_mock_jsm_issue(
        key: str = "IT-123",
        summary: str = "Printer broken",
        updated: str = "2023-01-01T12:00:00.000+0000",
        created: str = "2023-01-01T12:00:00.000+0000",
        description: str = "Printer on floor 3 is broken",
        labels: list[str] | None = None,
        project_key: str = "IT",
        project_name: str = "IT Service Desk",
        issuetype_name: str = "Service Request",
        comments: list[MagicMock] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        jsm_fields: dict[str, Any] | None = None,
    ) -> MagicMock:
        """Mock Issue whose raw fields carry JSM custom-field values."""
        mock_issue = MagicMock(spec=Issue)
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = summary
        mock_issue.fields.updated = updated
        mock_issue.fields.created = created
        mock_issue.fields.description = description
        mock_issue.fields.labels = labels or []

        mock_issue.fields.reporter = MagicMock()
        mock_issue.fields.reporter.displayName = "Test Reporter"
        mock_issue.fields.reporter.emailAddress = "reporter@example.com"

        mock_issue.fields.assignee = MagicMock()
        mock_issue.fields.assignee.displayName = "Test Agent"
        mock_issue.fields.assignee.emailAddress = "agent@example.com"

        mock_issue.fields.priority = MagicMock()
        mock_issue.fields.priority.name = "High"
        mock_issue.fields.status = MagicMock()
        mock_issue.fields.status.name = "Waiting for support"
        mock_issue.fields.resolution = None
        mock_issue.fields.duedate = None

        mock_issue.fields.project = MagicMock()
        mock_issue.fields.project.key = project_key
        mock_issue.fields.project.name = project_name

        mock_issue.fields.issuetype = MagicMock()
        mock_issue.fields.issuetype.name = issuetype_name
        mock_issue.fields.parent = None

        mock_issue.fields.comment = MagicMock()
        mock_issue.fields.comment.comments = comments or []

        raw_fields: dict[str, Any] = {
            "description": description,
            "attachment": attachments or [],
        }
        raw_fields.update(jsm_fields or {})
        mock_issue.raw = {"fields": raw_fields}

        return mock_issue

    return _create_mock_jsm_issue


def create_mock_comment(
    body: str,
    author_email: str = "customer@example.com",
    jsd_public: bool | None = None,
) -> MagicMock:
    """Mock comment resource; jsdPublic=False marks a JSM internal note."""
    comment = MagicMock()
    comment.body = body
    comment.author = MagicMock()
    comment.author.emailAddress = author_email
    raw: dict[str, Any] = {"body": body}
    if jsd_public is not None:
        raw["jsdPublic"] = jsd_public
    raw["author"] = {"emailAddress": author_email}
    comment.raw = raw
    return comment


def create_raw_jsm_issue(
    key: str = "IT-123",
    issue_id: str = "10001",
    summary: str = "Printer broken",
    project_key: str = "IT",
    project_name: str = "IT Service Desk",
    labels: list[str] | None = None,
    comments: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    jsm_fields: dict[str, Any] | None = None,
    jira_base_url: str = "https://jira.example.com",
) -> dict[str, Any]:
    """Raw issue payload for the Cloud bulkfetch path, where the connector
    builds real jira.resources.Issue objects via Issue(raw=...)."""
    raw_fields: dict[str, Any] = {
        "summary": summary,
        "updated": "2023-01-01T12:00:00.000+0000",
        "created": "2023-01-01T12:00:00.000+0000",
        # Cloud payloads carry descriptions as Atlassian Document Format.
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "cloud description"}],
                }
            ],
        },
        "labels": labels or [],
        "project": {"key": project_key, "name": project_name},
        "issuetype": {"name": "Service Request"},
        "parent": None,
        "comment": {"comments": comments or [], "total": len(comments or [])},
        "reporter": {
            "displayName": "Test Reporter",
            "emailAddress": "reporter@example.com",
        },
        "assignee": {
            "displayName": "Test Agent",
            "emailAddress": "agent@example.com",
        },
        "priority": {"name": "High"},
        "status": {"name": "Waiting for support"},
        "resolution": None,
        "duedate": None,
        "resolutiondate": None,
        "attachment": attachments or [],
    }
    raw_fields.update(jsm_fields or {})
    return {
        "id": issue_id,
        "key": key,
        "self": f"{jira_base_url}/rest/api/3/issue/{issue_id}",
        "fields": raw_fields,
    }


def create_raw_jsm_comment(
    body: str,
    author_email: str = "customer@example.com",
    jsd_public: bool | None = None,
    comment_id: str = "9001",
    jira_base_url: str = "https://jira.example.com",
) -> dict[str, Any]:
    """Raw cloud comment; the "self" link is required for the jira client to
    parse it into a resource carrying .raw (where jsdPublic lives)."""
    raw: dict[str, Any] = {
        "id": comment_id,
        "self": f"{jira_base_url}/rest/api/3/comment/{comment_id}",
        "body": body,
        "author": {"displayName": "Test Author", "emailAddress": author_email},
    }
    if jsd_public is not None:
        raw["jsdPublic"] = jsd_public
    return raw


def create_mock_attachment(
    attachment_id: str = "10001",
    filename: str = "report.pdf",
    mime_type: str = "application/pdf",
    size: int = 2048,
    jira_base_url: str = "https://jira.example.com",
) -> dict[str, Any]:
    return {
        "id": attachment_id,
        "filename": filename,
        "mimeType": mime_type,
        "size": size,
        "content": f"{jira_base_url}/rest/api/3/attachment/content/{attachment_id}",
        "created": "2023-01-02T12:00:00.000+0000",
        "author": {
            "displayName": "Test Agent",
            "emailAddress": "agent@example.com",
        },
    }
