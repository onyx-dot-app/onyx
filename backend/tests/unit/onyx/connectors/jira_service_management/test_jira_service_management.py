"""Tests for the Jira Service Management connector.

Mirrors the mocking conventions used by the existing Jira connector test
suite (backend/tests/unit/onyx/connectors/jira/) — a MagicMock(spec=JIRA)
client injected directly as `_jira_client`, no live credentials needed.
"""

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def jira_base_url() -> str:
    return "https://jira.example.com"


@pytest.fixture
def project_key() -> str:
    return "ITSM"


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    mock.project = MagicMock()
    mock.projects = MagicMock()
    mock._options = {"rest_api_version": "2"}
    return mock


@pytest.fixture
def jsm_connector(
    jira_base_url: str, project_key: str, mock_jira_client: MagicMock
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
    )
    connector._jira_client = mock_jira_client
    connector._jira_client.client_info.return_value = jira_base_url
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_issue() -> Callable[..., MagicMock]:
    def _create_mock_issue(
        key: str = "ITSM-1",
        summary: str = "Printer on 3rd floor is jammed",
        updated: str = "2023-01-01T12:00:00.000+0000",
        created: str = "2023-01-01T12:00:00.000+0000",
        description: str = "The printer needs a new toner cartridge.",
        project_key: str = "ITSM",
        project_name: str = "IT Service Management",
    ) -> MagicMock:
        mock_issue = MagicMock(spec=Issue)
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = summary
        mock_issue.fields.updated = updated
        mock_issue.fields.created = created
        mock_issue.fields.description = description
        mock_issue.fields.labels = []

        mock_issue.fields.reporter = MagicMock()
        mock_issue.fields.reporter.displayName = "Test Reporter"
        mock_issue.fields.reporter.emailAddress = "reporter@example.com"

        mock_issue.fields.assignee = None
        mock_issue.fields.priority = None
        mock_issue.fields.status = MagicMock()
        mock_issue.fields.status.name = "Open"
        mock_issue.fields.resolution = None

        mock_issue.fields.project = MagicMock()
        mock_issue.fields.project.key = project_key
        mock_issue.fields.project.name = project_name

        mock_issue.fields.issuetype = MagicMock()
        mock_issue.fields.issuetype.name = "Service Request"

        mock_issue.fields.parent = None
        mock_issue.raw = {"fields": {"description": description}}

        return mock_issue

    return _create_mock_issue


# --------------------------------------------------------------------------
# validate_connector_settings: the one genuinely JSM-specific check
# --------------------------------------------------------------------------


def test_validate_connector_settings_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    project = MagicMock()
    project.projectTypeKey = "service_desk"
    jsm_connector._jira_client.project.return_value = project  # ty: ignore[unresolved-attribute]

    jsm_connector.validate_connector_settings()  # should not raise

    jsm_connector._jira_client.project.assert_called_once_with("ITSM")  # ty: ignore[unresolved-attribute]


def test_validate_connector_settings_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    project = MagicMock()
    project.projectTypeKey = "software"
    jsm_connector._jira_client.project.return_value = project  # ty: ignore[unresolved-attribute]

    with pytest.raises(ConnectorValidationError) as excinfo:
        jsm_connector.validate_connector_settings()

    message = str(excinfo.value)
    assert "ITSM" in message
    assert "software" in message
    assert "not a Jira Service Management project" in message


def test_validate_connector_settings_skips_project_type_check_when_unset(
    jira_base_url: str, mock_jira_client: MagicMock
) -> None:
    """No project configured (indexing everything, or a custom JQL query) —
    there's no single project to type-check, so .project() must not be
    called at all."""
    connector = JiraServiceManagementConnector(jira_base_url=jira_base_url)
    connector._jira_client = mock_jira_client

    connector.validate_connector_settings()

    mock_jira_client.project.assert_not_called()


def test_validate_connector_settings_missing_project_type_key_is_permissive(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """If the Jira API response for some reason has no projectTypeKey at
    all, fail open rather than reject a possibly-valid project."""
    project = MagicMock()
    project.projectTypeKey = None
    jsm_connector._jira_client.project.return_value = project  # ty: ignore[unresolved-attribute]

    jsm_connector.validate_connector_settings()  # should not raise


# --------------------------------------------------------------------------
# Document source re-tagging
# --------------------------------------------------------------------------


def test_load_from_checkpoint_retags_document_source(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    mock_issue = create_mock_issue()
    search_issues_mock = jsm_connector._jira_client.search_issues  # ty: ignore[unresolved-attribute]
    search_issues_mock.return_value = [mock_issue]

    outputs = load_everything_from_checkpoint_connector(
        jsm_connector, 0, 10_000_000_000
    )

    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert documents[0].source != DocumentSource.JIRA


def test_load_from_checkpoint_with_perm_sync_retags_document_source(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    mock_issue = create_mock_issue()
    search_issues_mock = jsm_connector._jira_client.search_issues  # ty: ignore[unresolved-attribute]
    search_issues_mock.return_value = [mock_issue]

    with patch(
        "onyx.connectors.jira_service_management.connector.JiraServiceManagementConnector._get_project_permissions",
        return_value=None,
    ):
        checkpoint = jsm_connector.build_dummy_checkpoint()
        items = list(
            jsm_connector.load_from_checkpoint_with_perm_sync(
                0, 10_000_000_000, checkpoint
            )
        )

    documents = [item for item in items if isinstance(item, Document)]
    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_load_from_checkpoint_preserves_failures_and_checkpoint(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """ConnectorFailure items must pass through untouched (no source field
    to retag), and the final returned checkpoint must be the same object
    the parent JiraConnector produced — re-tagging shouldn't disturb it."""
    mock_issue = create_mock_issue()
    search_issues_mock = jsm_connector._jira_client.search_issues  # ty: ignore[unresolved-attribute]
    search_issues_mock.return_value = [mock_issue]

    checkpoint = jsm_connector.build_dummy_checkpoint()
    gen = jsm_connector.load_from_checkpoint(0, 10_000_000_000, checkpoint)
    items: list[Any] = []
    returned_checkpoint = None
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            returned_checkpoint = stop.value
            break

    assert not any(isinstance(item, ConnectorFailure) for item in items)
    assert returned_checkpoint is not None
    assert returned_checkpoint.has_more is not None
