from typing import Any
from unittest.mock import MagicMock
import pytest
from jira.resources import Issue

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class MockUser:
    def __init__(self, display_name: str, email: str | None = None) -> None:
        self.displayName = display_name
        if email:
            self.emailAddress = email


class MockComment:
    def __init__(
        self, body: str, author: MockUser, is_public: bool = True
    ) -> None:
        self.body = body
        self.author = author
        self.raw = {"body": body, "jsdPublic": is_public}


def make_mock_jsm_issue(
    key: str = "ITSM-101",
    summary: str = "VPN Connection Issue",
    description: str = "Unable to connect to the corporate VPN from remote office.",
    project_key: str = "ITSM",
    project_name: str = "IT Service Desk",
    request_type: str = "Get IT help",
    organizations: list[str] | None = None,
    slas: dict[str, Any] | None = None,
    comments: list[MockComment] | None = None,
    labels: list[str] | None = None,
) -> Issue:
    issue = MagicMock(spec=Issue)
    issue.key = key

    fields = MagicMock()
    fields.summary = summary
    fields.description = description
    fields.labels = labels or ["vpn", "networking"]
    fields.created = "2026-09-01T10:00:00.000+0000"
    fields.updated = "2026-09-02T14:30:00.000+0000"
    fields.duedate = "2026-09-05"
    fields.resolutiondate = None

    reporter = MockUser("Alice Requester", "alice@example.com")
    assignee = MockUser("Bob Agent", "bob@example.com")
    fields.reporter = reporter
    fields.assignee = assignee

    priority = MagicMock()
    priority.name = "High"
    fields.priority = priority

    status = MagicMock()
    status.name = "In Progress"
    fields.status = status

    fields.resolution = None

    issuetype = MagicMock()
    issuetype.name = "[System] Service Request"
    fields.issuetype = issuetype

    project = MagicMock()
    project.key = project_key
    project.name = project_name
    fields.project = project

    fields.parent = None

    if comments is None:
        comments = [
            MockComment(
                body="Please provide your operating system version.",
                author=assignee,
                is_public=True,
            ),
            MockComment(
                body="Checked RADIUS logs, user certificate expired.",
                author=assignee,
                is_public=False,
            ),
        ]

    comment_obj = MagicMock()
    comment_obj.comments = comments
    fields.comment = comment_obj

    issue.fields = fields

    # Mock raw representation for JSM fields
    raw_fields: dict[str, Any] = {
        "description": description,
        "customfield_10010": {
            "requestType": {"name": request_type},
        },
    }

    if organizations:
        raw_fields["organizations"] = [{"name": org} for org in organizations]

    if slas:
        raw_fields["customfield_10020"] = slas
    else:
        raw_fields["customfield_10020"] = {
            "name": "Time to first response",
            "completedCycles": [{"breached": False}],
        }
        raw_fields["customfield_10021"] = {
            "name": "Time to resolution",
            "ongoingCycle": {"breached": False},
        }

    issue.raw = {"fields": raw_fields}
    return issue


@pytest.fixture
def mock_jira_client() -> MagicMock:
    client = MagicMock()
    proj = MagicMock()
    proj.key = "ITSM"
    proj.name = "IT Service Desk"
    proj.projectTypeKey = "service_desk"
    client.project.return_value = proj
    return client


@pytest.fixture
def jsm_connector(mock_jira_client: MagicMock) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://support.example.com",
        project_key="ITSM",
    )
    connector._jira_client = mock_jira_client
    return connector
