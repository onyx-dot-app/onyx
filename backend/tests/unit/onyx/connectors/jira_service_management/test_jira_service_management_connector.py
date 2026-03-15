from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.utils import JSMQueue
from onyx.connectors.jira_service_management.utils import JSMRequestType
from onyx.connectors.jira_service_management.utils import JSMServiceDesk
from onyx.connectors.models import TextSection


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    mock.project = MagicMock()
    mock.projects = MagicMock()
    mock._options = {
        "server": "https://jira.example.com",
        "rest_api_version": JIRA_SERVER_API_VERSION,
    }
    mock._session = MagicMock()
    return mock


@pytest.fixture
def jsm_connector(mock_jira_client: MagicMock) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        comment_email_blacklist=["blacklist@example.com"],
    )
    connector._jira_client = mock_jira_client
    connector._service_desk_by_project_key = {
        "HELP": JSMServiceDesk(
            service_desk_id="1",
            project_key="HELP",
            project_name="Help Desk",
            project_id="10000",
            portal_id="1",
        ),
        "IT": JSMServiceDesk(
            service_desk_id="2",
            project_key="IT",
            project_name="IT Support",
            project_id="10001",
            portal_id="2",
        ),
    }
    yield connector


def _create_mock_issue(
    key: str = "HELP-1",
    project_key: str = "HELP",
    summary: str = "Password reset request",
) -> MagicMock:
    issue = MagicMock(spec=Issue)
    issue.key = key
    issue.raw = {"fields": {"description": "Reset my password"}}
    issue.fields = MagicMock()
    issue.fields.summary = summary
    issue.fields.updated = "2024-01-01T12:00:00.000+0000"
    issue.fields.description = "Reset my password"
    issue.fields.labels = []
    issue.fields.comment = MagicMock()
    issue.fields.comment.comments = [MagicMock(body="Initial customer comment")]
    issue.fields.reporter = MagicMock()
    issue.fields.reporter.displayName = "Alice Customer"
    issue.fields.reporter.emailAddress = "alice@example.com"
    issue.fields.assignee = MagicMock()
    issue.fields.assignee.displayName = "Bob Agent"
    issue.fields.assignee.emailAddress = "bob@example.com"
    issue.fields.priority = MagicMock()
    issue.fields.priority.name = "High"
    issue.fields.status = MagicMock()
    issue.fields.status.name = "Waiting for support"
    issue.fields.resolution = None
    issue.fields.duedate = None
    issue.fields.issuetype = MagicMock()
    issue.fields.issuetype.name = "Service Request"
    issue.fields.parent = None
    issue.fields.project = MagicMock()
    issue.fields.project.key = project_key
    issue.fields.project.name = "Help Desk"
    return issue


def test_get_jql_query_scopes_to_service_desk_projects(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()

    query = jsm_connector._get_jql_query(start, end)

    assert 'project in ("HELP", "IT")' in query
    assert "updated >= '2024-01-01 00:00'" in query
    assert "updated <= '2024-01-02 00:00'" in query


def test_process_issue_enriches_document_with_jsm_metadata(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = _create_mock_issue()

    with (
        patch(
            "onyx.connectors.jira_service_management.connector.get_customer_request",
            return_value={
                "issueId": "10001",
                "requestTypeId": "11",
                "currentStatus": {"status": "Waiting for support"},
                "reporter": {
                    "displayName": "Alice Customer",
                    "emailAddress": "alice@example.com",
                    "accountId": "acct-1",
                },
                "requestFieldValues": [
                    {"label": "Urgency", "value": "High"},
                    {"label": "Affected system", "value": "SSO"},
                ],
                "_links": {"web": "/servicedesk/customer/portal/1/HELP-1"},
            },
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_participants",
            return_value=[
                {
                    "displayName": "Charlie Collaborator",
                    "emailAddress": "charlie@example.com",
                }
            ],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_slas",
            return_value=[
                {
                    "name": "Time to resolution",
                    "ongoingCycle": {
                        "remainingTime": {"friendly": "2h"},
                        "elapsedTime": {"friendly": "30m"},
                        "breached": False,
                    },
                }
            ],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_approvals",
            return_value=[
                {"id": "77", "name": "Manager approval"}
            ],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.get_approval",
            return_value={
                "id": "77",
                "name": "Manager approval",
                "finalDecision": "approved",
                "approvers": [
                    {
                        "approver": {
                            "displayName": "Dana Manager",
                            "emailAddress": "dana@example.com",
                        }
                    }
                ],
            },
        ),
        patch.object(
            jsm_connector,
            "_get_request_type_map",
            return_value={
                "11": JSMRequestType(
                    request_type_id="11",
                    name="Access Request",
                    description="Request system access",
                    help_text="Use this for access requests",
                    issue_type_id="10010",
                    group_ids=("100",),
                )
            },
        ),
        patch.object(
            jsm_connector,
            "_get_request_queues",
            return_value=[
                JSMQueue(
                    queue_id="3",
                    name="Waiting for support",
                    jql="project = HELP",
                    issue_count=12,
                )
            ],
        ),
    ):
        document = jsm_connector._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id="HELP",
        )

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.metadata["jsm_service_desk"] == "Help Desk"
    assert document.metadata["jsm_request_type"] == "Access Request"
    assert document.metadata["jsm_customer"] == "Alice Customer"
    assert document.metadata["jsm_customer_email"] == "alice@example.com"
    assert document.metadata["jsm_queues"] == ["Waiting for support (12)"]
    assert document.metadata["jsm_slas"] == [
        "Time to resolution: elapsed 30m, remaining 2h"
    ]
    assert document.metadata["jsm_approvals"] == [
        "Manager approval: approved (Dana Manager)"
    ]
    assert document.secondary_owners is not None
    assert {owner.get_semantic_name() for owner in document.secondary_owners} == {
        "Charlie Collaborator",
        "Dana Manager",
    }

    section = document.sections[0]
    assert isinstance(section, TextSection)
    assert "Jira Service Management Details:" in section.text
    assert "Request type: Access Request" in section.text
    assert "Urgency: High" in section.text
    assert "Approvals:" in section.text
    assert "Portal URL: https://jira.example.com/servicedesk/customer/portal/1/HELP-1" in section.text


def test_process_issue_skips_non_request_issues(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = _create_mock_issue(key="HELP-2")

    with patch(
        "onyx.connectors.jira_service_management.connector.get_customer_request",
        return_value=None,
    ):
        document = jsm_connector._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id="HELP",
        )

    assert document is None


def test_process_issue_uses_issue_reporter_in_text_when_request_reporter_missing(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = _create_mock_issue()

    with (
        patch(
            "onyx.connectors.jira_service_management.connector.get_customer_request",
            return_value={
                "issueId": "10001",
                "requestFieldValues": [],
                "_links": {"web": "/servicedesk/customer/portal/1/HELP-1"},
                "reporter": {},
            },
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_participants",
            return_value=[],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_slas",
            return_value=[],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_approvals",
            return_value=[],
        ),
        patch.object(jsm_connector, "_get_request_type_map", return_value={}),
        patch.object(jsm_connector, "_get_request_queues", return_value=[]),
    ):
        document = jsm_connector._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id="HELP",
        )

    assert document is not None
    section = document.sections[0]
    assert isinstance(section, TextSection)
    assert "Customer: Alice Customer (alice@example.com)" in section.text
    assert document.metadata["jsm_customer"] == "Alice Customer"


def test_process_issue_omits_agent_link_when_customer_portal_url_missing(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = _create_mock_issue()

    with (
        patch(
            "onyx.connectors.jira_service_management.connector.get_customer_request",
            return_value={
                "issueId": "10001",
                "requestFieldValues": [],
                "_links": {"agent": "/browse/HELP-1"},
                "reporter": {},
            },
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_participants",
            return_value=[],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_slas",
            return_value=[],
        ),
        patch(
            "onyx.connectors.jira_service_management.connector.list_request_approvals",
            return_value=[],
        ),
        patch.object(jsm_connector, "_get_request_type_map", return_value={}),
        patch.object(jsm_connector, "_get_request_queues", return_value=[]),
    ):
        document = jsm_connector._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id="HELP",
        )

    assert document is not None
    assert "jsm_request_portal_url" not in document.metadata
    section = document.sections[0]
    assert isinstance(section, TextSection)
    assert "Portal URL:" not in section.text


def test_get_jql_query_raises_runtime_error_when_service_desks_become_unavailable(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector._service_desk_by_project_key = {}
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()

    with pytest.raises(RuntimeError, match="Re-validate the connector settings"):
        jsm_connector._get_jql_query(start, end)


def test_get_request_type_map_retries_after_transient_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 429
    response._content = b"{}"
    error = requests.HTTPError(response=response)
    expected = JSMRequestType(
        request_type_id="11",
        name="Access Request",
        description=None,
        help_text=None,
        issue_type_id=None,
        group_ids=(),
    )

    with patch(
        "onyx.connectors.jira_service_management.connector.list_request_types",
        side_effect=[error, [expected]],
    ):
        first = jsm_connector._get_request_type_map("1")
        second = jsm_connector._get_request_type_map("1")

    assert first == {}
    assert second == {"11": expected}


def test_get_request_type_map_stops_retrying_after_second_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 429
    response._content = b"{}"
    error = requests.HTTPError(response=response)

    with patch(
        "onyx.connectors.jira_service_management.connector.list_request_types",
        side_effect=[error, error],
    ) as mock_list_request_types:
        first = jsm_connector._get_request_type_map("1")
        second = jsm_connector._get_request_type_map("1")
        third = jsm_connector._get_request_type_map("1")

    assert first == {}
    assert second == {}
    assert third == {}
    assert mock_list_request_types.call_count == 2


def test_get_request_type_map_stops_after_first_non_retryable_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 403
    response._content = b"{}"
    error = requests.HTTPError(response=response)

    with patch(
        "onyx.connectors.jira_service_management.connector.list_request_types",
        side_effect=error,
    ) as mock_list_request_types:
        first = jsm_connector._get_request_type_map("1")
        second = jsm_connector._get_request_type_map("1")

    assert first == {}
    assert second == {}
    assert mock_list_request_types.call_count == 1


def test_get_request_queues_retries_after_transient_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 503
    response._content = b"{}"
    error = requests.HTTPError(response=response)
    queue = JSMQueue(
        queue_id="3",
        name="Waiting for support",
        jql="project = HELP",
        issue_count=12,
    )

    with patch(
        "onyx.connectors.jira_service_management.connector.build_queue_membership_map",
        side_effect=[error, {"HELP-1": [queue]}],
    ):
        first = jsm_connector._get_request_queues("1", "HELP-1")
        second = jsm_connector._get_request_queues("1", "HELP-1")

    assert first == []
    assert second == [queue]


def test_get_request_queues_stop_retrying_after_second_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 503
    response._content = b"{}"
    error = requests.HTTPError(response=response)

    with patch(
        "onyx.connectors.jira_service_management.connector.build_queue_membership_map",
        side_effect=[error, error],
    ) as mock_build_queue_membership_map:
        first = jsm_connector._get_request_queues("1", "HELP-1")
        second = jsm_connector._get_request_queues("1", "HELP-1")
        third = jsm_connector._get_request_queues("1", "HELP-1")

    assert first == []
    assert second == []
    assert third == []
    assert mock_build_queue_membership_map.call_count == 2


def test_get_request_queues_stop_after_first_non_retryable_http_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    response = requests.Response()
    response.status_code = 403
    response._content = b"{}"
    error = requests.HTTPError(response=response)

    with patch(
        "onyx.connectors.jira_service_management.connector.build_queue_membership_map",
        side_effect=error,
    ) as mock_build_queue_membership_map:
        first = jsm_connector._get_request_queues("1", "HELP-1")
        second = jsm_connector._get_request_queues("1", "HELP-1")

    assert first == []
    assert second == []
    assert mock_build_queue_membership_map.call_count == 1
