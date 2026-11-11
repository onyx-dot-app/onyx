"""Unit tests for the Jira Service Management connector.

The gateway is a fake. These tests do not call Jira.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)

_BASE_URL = "https://jira.example.com"
_START = 1_672_531_200.0
_END = 1_672_617_600.0


def _gateway(*, cloud: bool) -> MagicMock:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = cloud
    gateway.list_fields.return_value = []
    gateway.list_projects.return_value = []
    return gateway


def _connector(
    gateway: MagicMock,
    *,
    project_key: str | None = "IT",
    jql_query: str | None = None,
    comment_email_blacklist: list[str] | None = None,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL,
        project_key=project_key,
        jql_query=jql_query,
        comment_email_blacklist=comment_email_blacklist,
    )
    connector._source_operations = gateway
    return connector


def _issue(**extra_fields: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": "VPN access",
        "updated": "2023-01-01T12:00:00.000+0000",
        "created": "2023-01-01T11:00:00.000+0000",
        "description": "Cannot connect.",
        "labels": [],
        "reporter": {"displayName": "Ada", "emailAddress": "ada@example.com"},
        "assignee": None,
        "priority": {"name": "High"},
        "status": {"name": "Waiting for support"},
        "resolution": None,
        "project": {"key": "IT", "name": "IT Help"},
        "issuetype": {"name": "Request"},
        "parent": None,
        "comment": {"comments": [], "total": 0},
    }
    fields.update(extra_fields)
    return {"id": "1", "key": "IT-1", "fields": fields}


def _catalog() -> list[dict[str, str | dict[str, str]]]:
    def field(field_id: str, custom: str) -> dict[str, str | dict[str, str]]:
        return {"id": field_id, "schema": {"custom": custom}}

    return [
        field("customfield_10010", "com.atlassian.servicedesk:vp-origin"),
        field(
            "customfield_10011", "com.atlassian.servicedesk:sd-customer-organizations"
        ),
        field("customfield_10012", "com.atlassian.servicedesk:sd-request-participants"),
        field("customfield_10013", "com.atlassian.servicedesk:sd-sla-field"),
    ]


def _service_desk_issue() -> dict[str, Any]:
    return _issue(
        customfield_10010={
            "requestType": {
                "name": "Get IT help",
                "serviceDeskId": "4",
            },
            "currentStatus": {"status": "Waiting for customer"},
        },
        customfield_10011=[{"name": "Acme"}],
        customfield_10012=[{"displayName": "Jane Doe"}],
        customfield_10013={
            "name": "Time to resolution",
            "ongoingCycle": {
                "breached": True,
                "remainingTime": {"friendly": "0m"},
            },
            "completedCycles": [{"breached": False}],
        },
        comment={
            "total": 3,
            "comments": [
                {
                    "author": {"emailAddress": "ada@example.com"},
                    "body": "Still blocked.",
                    "jsdPublic": True,
                },
                {
                    "author": {"emailAddress": "agent@example.com"},
                    "body": "Check the firewall.",
                    "jsdPublic": False,
                },
                {
                    "author": {"emailAddress": "bot@example.com"},
                    "body": "Automated reply.",
                    "jsdPublic": True,
                },
            ],
        },
    )


def _documents(connector: JiraServiceManagementConnector) -> list[Document]:
    return [
        item
        for batch in load_everything_from_checkpoint_connector(connector, _START, _END)
        for item in batch.items
        if isinstance(item, Document)
    ]


def test_blank_project_key_and_jql_are_rejected() -> None:
    with pytest.raises(ConnectorValidationError, match="Project key cannot be blank"):
        JiraServiceManagementConnector(jira_base_url=_BASE_URL, project_key="  ")
    with pytest.raises(ConnectorValidationError, match="JQL query cannot be blank"):
        JiraServiceManagementConnector(
            jira_base_url=_BASE_URL, project_key=None, jql_query=" \n "
        )
    with pytest.raises(ValidationError, match="Project key cannot be blank"):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": _BASE_URL, "project_key": " "}
        )
    with pytest.raises(ValidationError, match="JQL query cannot be blank"):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": _BASE_URL, "jql_query": " "}
        )


def test_project_key_is_normalized_and_rejected_when_unsafe() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL, project_key=" it "
    )

    assert connector.jira_project == "IT"
    with pytest.raises(ConnectorValidationError, match="Project key"):
        JiraServiceManagementConnector(jira_base_url=_BASE_URL, project_key='IT" OR ')


def test_config_uppercases_a_project_key_and_rejects_jql_order_by() -> None:
    config = JiraServiceManagementConnectorConfig.model_validate(
        {"jira_base_url": _BASE_URL, "project_key": "it"}
    )

    assert config.project_key == "IT"
    with pytest.raises(ValidationError, match="Project key"):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": _BASE_URL, "project_key": "bad key"}
        )


def test_cloud_poll_scopes_to_service_desk_projects() -> None:
    gateway = _gateway(cloud=True)
    connector = _connector(gateway, project_key=None, jql_query="summary ~ vpn")

    query = connector._get_jql_query(_START, _END)

    assert "projectType = service_desk" in query
    assert "(summary ~ vpn)" in query
    assert f"updated >= {int(_START * 1000)}" in query
    assert f"updated <= {int(_END * 1000)}" in query
    assert "project IN" not in query
    gateway.list_projects.assert_not_called()


def test_server_poll_names_only_service_desk_projects() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"},
        {"key": "SOFT", "projectTypeKey": "software"},
        {"key": "HR"},
    ]
    gateway.get_project.return_value = {"key": "HR", "projectTypeKey": "service_desk"}
    connector = _connector(gateway, project_key=None)

    query = connector._get_jql_query(_START, _END)

    assert 'project IN ("IT", "HR")' in query
    assert "SOFT" not in query
    assert "projectType" not in query
    gateway.get_project.assert_called_once_with(project_key="HR")


def test_server_poll_fails_when_no_service_desk_is_visible() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [{"key": "SOFT", "projectTypeKey": "software"}]
    connector = _connector(gateway, project_key=None)

    with pytest.raises(ConnectorValidationError, match="No Jira Service Management"):
        connector._get_jql_query(_START, _END)


def test_validation_rejects_a_software_project() -> None:
    gateway = _gateway(cloud=True)
    gateway.get_project.return_value = {"key": "SOFT", "projectTypeKey": "software"}
    connector = _connector(gateway, project_key="SOFT")

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        connector.validate_connector_settings()


def test_cloud_validation_without_a_project_runs_the_service_desk_query() -> None:
    gateway = _gateway(cloud=True)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"}
    ]
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token=None
    )
    connector = _connector(gateway, project_key=None)

    connector.validate_connector_settings()

    jql = gateway.search_issue_ids.call_args.kwargs["jql"]
    assert "projectType = service_desk" in jql
    assert "project =" not in jql


def test_validation_accepts_a_service_desk_project() -> None:
    gateway = _gateway(cloud=False)
    gateway.get_project.return_value = {"key": "IT", "projectTypeKey": "service_desk"}
    connector = _connector(gateway)

    connector.validate_connector_settings()

    gateway.get_project.assert_called_once_with(project_key="IT")
    gateway.search_issues.assert_not_called()


def test_indexed_request_carries_service_desk_fields_and_comment_visibility() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"}
    ]
    gateway.list_fields.return_value = _catalog()
    gateway.search_issues.return_value = [_service_desk_issue()]
    connector = _connector(gateway, comment_email_blacklist=["bot@example.com"])

    documents = _documents(connector)

    assert len(documents) == 1
    document = documents[0]
    assert document.source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == f"{_BASE_URL}/browse/IT-1"
    assert document.metadata["request_type"] == "Get IT help"
    assert document.metadata["customer_status"] == "Waiting for customer"
    assert document.metadata["organizations"] == ["Acme"]
    assert document.metadata["request_participants"] == ["Jane Doe"]
    assert document.metadata["sla_breached"] == "true"
    assert document.metadata["service_desk_id"] == "4"
    assert (
        document.metadata["customer_portal_url"]
        == f"{_BASE_URL}/servicedesk/customer/portal/4/IT-1"
    )
    section_text = document.sections[0].text
    assert isinstance(section_text, str)
    assert "Request type: Get IT help" in section_text
    assert "Comment: Still blocked." in section_text
    assert "Comment (internal): Check the firewall." in section_text
    assert "Automated reply" not in section_text
    assert "Cannot connect." in section_text


def test_truncated_comments_are_paged() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"}
    ]
    gateway.search_issues.return_value = [
        _issue(
            comment={
                "total": 2,
                "comments": [
                    {"author": {"emailAddress": "ada@example.com"}, "body": "First."}
                ],
            }
        )
    ]
    gateway.list_issue_comments.return_value = {
        "total": 2,
        "comments": [
            {"author": {"emailAddress": "ada@example.com"}, "body": "First."},
            {
                "author": {"emailAddress": "agent@example.com"},
                "body": "Second.",
                "jsdPublic": False,
            },
        ],
    }
    connector = _connector(gateway)

    section_text = _documents(connector)[0].sections[0].text
    assert isinstance(section_text, str)

    assert "Comment: First." in section_text
    assert "Comment (internal): Second." in section_text
    gateway.list_issue_comments.assert_called_once_with(
        issue_key="IT-1", start_at=0, max_results=100
    )


def test_comment_page_failure_keeps_the_embedded_comments() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"}
    ]
    gateway.search_issues.return_value = [
        _issue(
            comment={
                "total": 2,
                "comments": [
                    {"author": {"emailAddress": "ada@example.com"}, "body": "First."}
                ],
            }
        )
    ]
    gateway.list_issue_comments.side_effect = JiraApiError(
        "unavailable", status_code=500, body="nope"
    )
    connector = _connector(gateway)

    documents = _documents(connector)

    assert len(documents) == 1
    section_text = documents[0].sections[0].text
    assert isinstance(section_text, str)
    assert "Comment: First." in section_text


def test_auth_failure_on_comments_fails_that_request() -> None:
    gateway = _gateway(cloud=False)
    gateway.list_projects.return_value = [
        {"key": "IT", "projectTypeKey": "service_desk"}
    ]
    gateway.search_issues.return_value = [
        _issue(
            comment={
                "total": 2,
                "comments": [
                    {"author": {"emailAddress": "ada@example.com"}, "body": "First."}
                ],
            }
        )
    ]
    gateway.list_issue_comments.side_effect = JiraApiError(
        "expired", status_code=401, body="unauthorized"
    )
    connector = _connector(gateway)

    items: list[Document | ConnectorFailure] = []
    for batch in load_everything_from_checkpoint_connector(connector, _START, _END):
        items.extend(batch.items)

    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)
    assert items[0].failed_document is not None
    assert items[0].failed_document.document_id == f"{_BASE_URL}/browse/IT-1"
