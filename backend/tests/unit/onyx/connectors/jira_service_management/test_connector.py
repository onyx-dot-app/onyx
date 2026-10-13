from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def mock_source_operations() -> MagicMock:
    mock_client = MagicMock(spec=JiraSourceOperations)
    mock_client._is_cloud.return_value = False
    mock_client.search_issues = MagicMock(return_value=[])
    mock_client.get_project = MagicMock()
    return mock_client


@pytest.fixture
def make_issue() -> Callable[..., dict[str, Any]]:
    def _make_issue(
        key: str = "HELP-1", summary: str = "Printer is jammed"
    ) -> dict[str, Any]:
        return {
            "key": key,
            "fields": {
                "summary": summary,
                "updated": "2026-05-01T12:00:00.000+0000",
                "created": "2026-04-30T09:00:00.000+0000",
                "description": "The printer is stuck.",
                "labels": [],
                "comment": {"comments": []},
                "reporter": None,
                "assignee": None,
                "priority": None,
                "status": None,
                "resolution": None,
                "duedate": None,
                "issuetype": {"name": "Service Request"},
                "parent": None,
                "project": {"key": "HELP", "name": "Help Desk"},
            },
        }

    return _make_issue


def _connector(
    mock_source_operations: MagicMock,
    *,
    project_key: str | None = None,
    jql_query: str | None = None,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key=project_key,
        jql_query=jql_query,
    )
    connector._source_operations = mock_source_operations
    return connector


def test_registry_maps_to_jsm_connector() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]

    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"


def test_jql_restricts_everything_to_service_desk(
    mock_source_operations: MagicMock,
) -> None:
    connector = _connector(mock_source_operations)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        "spaceType = service_desk AND "
        "updated >= 1777593600000 AND updated <= 1777680000000"
    )


def test_jql_validates_project_scope_without_hot_path_service_desk_call(
    mock_source_operations: MagicMock,
) -> None:
    connector = _connector(mock_source_operations, project_key="HELP")
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        'project = "HELP" AND updated >= 1777593600000 AND updated <= 1777680000000'
    )

    assert mock_source_operations.get_project.call_count == 0


def test_custom_jql_is_always_scoped_to_service_desk(
    mock_source_operations: MagicMock,
) -> None:
    connector = _connector(
        mock_source_operations, jql_query='status = "Waiting for support"'
    )
    start = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp()

    assert connector._get_jql_query(start, end) == (
        '(status = "Waiting for support") AND spaceType = service_desk AND '
        "updated >= 1777593600000 AND updated <= 1777680000000"
    )


def test_validate_all_projects_uses_official_service_space_jql(
    mock_source_operations: MagicMock,
) -> None:
    connector = _connector(mock_source_operations)

    connector.validate_connector_settings()

    mock_source_operations.search_issues.assert_called_once()
    assert (
        mock_source_operations.search_issues.call_args.kwargs["jql"]
        == "spaceType = service_desk"
    )


def test_validate_custom_jql_is_parenthesized_and_scoped(
    mock_source_operations: MagicMock,
) -> None:
    connector = _connector(
        mock_source_operations, jql_query='status = "Open" OR priority = High'
    )

    connector.validate_connector_settings()

    mock_source_operations.search_issues.assert_called_once()
    assert mock_source_operations.search_issues.call_args.kwargs["jql"] == (
        '(status = "Open" OR priority = High) AND spaceType = service_desk'
    )


def test_validate_project_rejects_non_jsm_project(
    mock_source_operations: MagicMock,
) -> None:
    project = {"projectTypeKey": "software"}
    mock_source_operations.get_project.return_value = project
    connector = _connector(mock_source_operations, project_key="ENG")

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        connector.validate_connector_settings()

    mock_source_operations.get_project.assert_called_once_with(project_key="ENG")


def test_validate_project_accepts_service_desk_project(
    mock_source_operations: MagicMock,
) -> None:
    project = {"projectTypeKey": "service_desk"}
    mock_source_operations.get_project.return_value = project
    connector = _connector(mock_source_operations, project_key="HELP")

    connector.validate_connector_settings()

    mock_source_operations.get_project.assert_called_once_with(project_key="HELP")
    mock_source_operations.search_issues.assert_not_called()


def test_validate_project_accepts_service_management_alias(
    mock_source_operations: MagicMock,
) -> None:
    project = {"projectTypeKey": "service_management"}
    mock_source_operations.get_project.return_value = project
    connector = _connector(mock_source_operations, project_key="HELP")

    connector.validate_connector_settings()

    mock_source_operations.get_project.assert_called_once_with(project_key="HELP")


def test_missing_credentials_names_jsm_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
    )

    with pytest.raises(
        ConnectorMissingCredentialError, match="Jira Service Management"
    ):
        connector.validate_connector_settings()


def test_documents_are_indexed_with_jsm_source(
    mock_source_operations: MagicMock,
    make_issue: Callable[..., dict[str, Any]],
) -> None:
    mock_source_operations.search_issues.return_value = [make_issue()]
    connector = _connector(mock_source_operations, project_key="HELP")

    outputs = load_everything_from_checkpoint_connector(
        connector,
        start=0,
        end=datetime(2026, 5, 2, tzinfo=timezone.utc).timestamp(),
    )

    document = cast(Document, outputs[0].items[0])
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == "https://jira.example.com/browse/HELP-1"
    assert document.doc_created_at == datetime(2026, 4, 30, 9, tzinfo=timezone.utc)
    assert outputs[0].next_checkpoint.has_more is False
