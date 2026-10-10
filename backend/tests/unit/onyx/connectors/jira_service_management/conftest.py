from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from jira import JIRA

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.utils import JsmFieldMap

TEST_BASE_URL = "https://support.example.com"
TEST_PROJECT_KEY = "HELP"

# Custom field IDs as they'd appear on a real (cloud) Jira instance; the
# connector must discover these by name, never hard-code them.
REQUEST_TYPE_FIELD_ID = "customfield_10010"
ORGANIZATIONS_FIELD_ID = "customfield_10001"
SLA_FIRST_RESPONSE_FIELD_ID = "customfield_10020"
SLA_RESOLUTION_FIELD_ID = "customfield_10021"


@pytest.fixture
def jira_base_url() -> str:
    return TEST_BASE_URL


@pytest.fixture
def project_key() -> str:
    return TEST_PROJECT_KEY


@pytest.fixture
def jsm_field_map() -> JsmFieldMap:
    return JsmFieldMap(
        customer_request_type=REQUEST_TYPE_FIELD_ID,
        organizations=ORGANIZATIONS_FIELD_ID,
    )


class MockUser:
    def __init__(self, display_name: str, email: str | None = None) -> None:
        self.displayName = display_name
        if email:
            self.emailAddress = email


class MockComment:
    def __init__(
        self,
        body: str,
        author: MockUser | None = None,
        is_public: bool = True,
    ) -> None:
        self.body = body
        if author is not None:
            self.author = author
        self.raw = {"body": body, "jsdPublic": is_public}


class MockJiraIssue(dict[str, Any]):
    """Raw Jira issue with a legacy key accessor for test call sites."""

    @property
    def key(self) -> str:
        return str(self["key"])

    @property
    def raw(self) -> dict[str, Any]:
        return self


def make_mock_jsm_issue(
    key: str = "HELP-101",
    summary: str = "VPN not connecting",
    description: str = "Unable to connect to the corporate VPN.",
    project_key: str = TEST_PROJECT_KEY,
    project_name: str = "IT Help Desk",
    labels: list[str] | None = None,
    comments: list[MockComment] | None = None,
    request_type: str | None = "Get IT help",
    organizations: list[str] | None = None,
    slas: dict[str, Any] | None = None,
    field_map: JsmFieldMap | None = None,
    raw_overrides: dict[str, Any] | None = None,
    created: str = "2026-09-01T10:00:00.000+0000",
    updated: str = "2026-09-02T14:30:00.000+0000",
) -> MockJiraIssue:
    """Build a raw REST issue matching JiraSourceOperations' dictionary contract."""
    if comments is None:
        comments = [
            MockComment(
                body="Have you tried restarting your laptop?",
                author=MockUser("Bob Agent", "bob@example.com"),
                is_public=True,
            ),
            MockComment(
                body="Checked the VPN gateway logs; cert expired.",
                author=MockUser("Bob Agent", "bob@example.com"),
                is_public=False,
            ),
        ]
    if field_map is None:
        field_map = JsmFieldMap(
            customer_request_type=REQUEST_TYPE_FIELD_ID,
            organizations=ORGANIZATIONS_FIELD_ID,
        )

    raw_fields: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "labels": labels or [],
        "created": created,
        "updated": updated,
        "reporter": {"displayName": "Alice Requester", "emailAddress": "alice@example.com"},
        "assignee": {"displayName": "Bob Agent", "emailAddress": "bob@example.com"},
        "priority": {"name": "High"},
        "status": {"name": "Waiting for support"},
        "resolution": None,
        "duedate": None,
        "resolutiondate": None,
        "issuetype": {"name": "Service Request"},
        "project": {"key": project_key, "name": project_name},
        "parent": None,
        "comment": {
            "comments": [
                {
                    "body": comment.body,
                    "author": (
                        {
                            "displayName": comment.author.displayName,
                            "emailAddress": getattr(comment.author, "emailAddress", None),
                        }
                        if hasattr(comment, "author")
                        else {}
                    ),
                    "jsdPublic": comment.raw.get("jsdPublic", True),
                }
                for comment in comments
            ]
        },
    }

    if request_type is not None and field_map.customer_request_type:
        raw_fields[field_map.customer_request_type] = request_type
    if organizations is not None and field_map.organizations:
        raw_fields[field_map.organizations] = [
            {"id": str(i + 1), "name": org}
            for i, org in enumerate(organizations)
        ]
    if slas is not None:
        raw_fields.update(slas)
    if raw_overrides:
        raw_fields.update(raw_overrides)

    return MockJiraIssue(key=key, fields=raw_fields)


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    mock.project = MagicMock()
    mock.projects = MagicMock()
    mock.fields = MagicMock()
    return mock


@pytest.fixture
def make_jsm_connector(
    mock_jira_client: MagicMock,
) -> Callable[..., JiraServiceManagementConnector]:
    """Factory fixture producing a JSM connector backed by the mock client."""

    def _make(
        project_key: str = TEST_PROJECT_KEY,
        **kwargs: Any,
    ) -> JiraServiceManagementConnector:
        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL,
            project_key=project_key,
            comment_email_blacklist=kwargs.pop("comment_email_blacklist", []),
            **kwargs,
        )
        # The production Jira connector uses a credential-scoped operations
        # gateway; route the legacy test mock through the same public methods.
        from onyx.connectors.jira.source_operations import JiraSourceOperations

        gateway = MagicMock(spec=JiraSourceOperations)
        gateway._is_cloud.return_value = False

        def search_issues(
            *, jql: str, start_at: int, max_results: int, fields: str | None = None
        ) -> list[dict[str, Any]]:
            issues = mock_jira_client.search_issues(
                jql_str=jql,
                startAt=start_at,
                maxResults=max_results,
                fields=fields,
            )
            return [issue.raw if hasattr(issue, "raw") else issue for issue in issues]

        attachment_cache: dict[str, Any] = {}

        def list_issue_attachments(*, issue_key: str) -> list[dict[str, Any]]:
            result = mock_jira_client.issue(issue_key, fields="attachment")
            attachments = result.fields.attachment or []
            metadata = []
            for attachment in attachments:
                attachment_id = str(attachment.id)
                attachment_cache[attachment_id] = attachment
                metadata.append({
                    "id": attachment_id,
                    "filename": attachment.filename,
                    "size": attachment.size,
                    "mimeType": attachment.mimeType,
                    "created": attachment.created,
                    "content": attachment.content,
                })
            return metadata

        def download_attachment(*, attachment_id: str) -> bytes:
            return attachment_cache[attachment_id].get()

        def get_project(*, project_key: str) -> dict[str, Any]:
            project = mock_jira_client.project(project_key)
            if isinstance(project, dict):
                return project
            return {
                "key": project_key,
                "projectTypeKey": getattr(project, "projectTypeKey", None),
            }

        gateway.search_issues.side_effect = search_issues
        gateway.list_fields.side_effect = lambda: mock_jira_client.fields()
        gateway.list_issue_attachments.side_effect = list_issue_attachments
        gateway.download_attachment.side_effect = download_attachment
        gateway.get_project.side_effect = get_project
        connector._source_operations = gateway
        connector._jira_client = mock_jira_client  # Legacy assertions only.
        return connector

    return _make
