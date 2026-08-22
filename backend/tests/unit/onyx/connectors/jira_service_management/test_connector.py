from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import cast
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock_client = MagicMock(spec=JIRA)
    mock_client._options = {"rest_api_version": JIRA_SERVER_API_VERSION}
    mock_client.search_issues = MagicMock(return_value=[])
    mock_client.project = MagicMock()
    return mock_client


@pytest.fixture
def make_issue() -> Callable[..., MagicMock]:
    def _make_issue(
        key: str = "HELP-1", summary: str = "Printer is jammed"
    ) -> MagicMock:
        issue = MagicMock(spec=Issue)
        issue.key = key
        issue.fields = MagicMock()
        issue.fields.summary = summary
        issue.fields.updated = "2026-05-01T12:00:00.000+0000"
        issue.fields.description = "The printer is stuck."
        issue.fields.labels = []
        issue.fields.comment.comments = []
        issue.fields.reporter = None
        issue.fields.assignee = None
        issue.fields.priority = None
        issue.fields.status = None
        issue.fields.resolution = None
        issue.fields.created = None
        issue.fields.duedate = None
        issue.fields.issuetype = MagicMock()
        issue.fields.issuetype.name = "Service Request"
        issue.fields.parent = None
        issue.fields.project = MagicMock()
        issue.fields.project.key = "HELP"
        issue.fields.project.name = "Help Desk"
        issue.raw = {"fields": {"description": issue.fields.description}}
        return issue

    return _make_issue


def _connector(
    mock_jira_client: MagicMock, **kwargs: object
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        **kwargs,
    )
    connector._jira_client = mock_jira_client
    return connector


def test_registry_maps_to_jsm_connector() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]

    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"


def test_jql_restricts_everything_to_service_desk(
    mock_jira_client: MagicMock,
) -> None:
    connector = _connector(mock_jira_client)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        "spaceType = service_desk AND "
        "updated >= '2026-05-01 00:00' AND updated <= '2026-05-02 00:00'"
    )


def test_jql_validates_project_scope_without_hot_path_service_desk_call(
    mock_jira_client: MagicMock,
) -> None:
    connector = _connector(mock_jira_client, project_key="HELP")
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        'project = "HELP" AND '
        "updated >= '2026-05-01 00:00' AND updated <= '2026-05-02 00:00'"
    )

    assert mock_jira_client.project.call_count == 0


def test_custom_jql_is_always_scoped_to_service_desk(
    mock_jira_client: MagicMock,
) -> None:
    connector = _connector(mock_jira_client, jql_query='status = "Waiting for support"')
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        '(status = "Waiting for support") AND spaceType = service_desk AND '
        "updated >= '2026-05-01 00:00' AND updated <= '2026-05-02 00:00'"
    )


def test_validate_all_projects_uses_official_service_space_jql(
    mock_jira_client: MagicMock,
) -> None:
    connector = _connector(mock_jira_client)

    connector.validate_connector_settings()

    mock_jira_client.search_issues.assert_called_once()
    assert (
        mock_jira_client.search_issues.call_args.kwargs["jql_str"]
        == "spaceType = service_desk"
    )


def test_validate_custom_jql_is_parenthesized_and_scoped(
    mock_jira_client: MagicMock,
) -> None:
    connector = _connector(
        mock_jira_client, jql_query='status = "Open" OR priority = High'
    )

    connector.validate_connector_settings()

    mock_jira_client.search_issues.assert_called_once()
    assert mock_jira_client.search_issues.call_args.kwargs["jql_str"] == (
        '(status = "Open" OR priority = High) AND spaceType = service_desk'
    )


def test_validate_project_rejects_non_jsm_project(mock_jira_client: MagicMock) -> None:
    project = MagicMock()
    project.projectTypeKey = "software"
    mock_jira_client.project.return_value = project
    connector = _connector(mock_jira_client, project_key="ENG")

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        connector.validate_connector_settings()

    mock_jira_client.project.assert_called_once_with("ENG")


def test_validate_project_accepts_service_desk_project(
    mock_jira_client: MagicMock,
) -> None:
    project = MagicMock()
    project.projectTypeKey = "service_desk"
    mock_jira_client.project.return_value = project
    connector = _connector(mock_jira_client, project_key="HELP")

    connector.validate_connector_settings()

    mock_jira_client.project.assert_called_once_with("HELP")
    mock_jira_client.search_issues.assert_not_called()


def test_validate_project_accepts_raw_service_management_alias(
    mock_jira_client: MagicMock,
) -> None:
    project = MagicMock()
    project.projectTypeKey = None
    project.raw = {"projectTypeKey": "service_management"}
    mock_jira_client.project.return_value = project
    connector = _connector(mock_jira_client, project_key="HELP")

    connector.validate_connector_settings()

    mock_jira_client.project.assert_called_once_with("HELP")


def test_missing_credentials_names_jsm_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )

    with pytest.raises(
        ConnectorMissingCredentialError, match="Jira Service Management"
    ):
        connector.validate_connector_settings()


def test_documents_are_indexed_with_jsm_source(
    mock_jira_client: MagicMock,
    make_issue: Callable[..., MagicMock],
) -> None:
    mock_jira_client.search_issues.return_value = [make_issue()]
    connector = _connector(mock_jira_client, project_key="HELP")

    outputs = load_everything_from_checkpoint_connector(
        connector,
        start=0,
        end=datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp(),
    )

    document = cast(Document, outputs[0].items[0])
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == "https://jira.example.com/browse/HELP-1"
    assert outputs[0].next_checkpoint.has_more is False
