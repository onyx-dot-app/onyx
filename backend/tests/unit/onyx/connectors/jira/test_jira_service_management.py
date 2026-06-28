"""Tests for the Jira Service Management connector.

Covers:
- Document source tagging (JSM vs plain Jira)
- JSM-specific JQL generation (project type filter, project key filter)
- Subclass invariants (source cannot be overridden)
- validate_connector_settings: rejects non-JSM projects
- Registry mapping
- process_jira_issue source plumbing
"""
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraServiceManagementConnector,
    process_jira_issue,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_issue() -> MagicMock:
    """Minimal mock Issue sufficient for process_jira_issue."""
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "Customer cannot log in to the portal"
    fields.comment = MagicMock()
    fields.comment.comments = [
        MagicMock(body="Investigating now", author=MagicMock(emailAddress="agent@example.com")),
    ]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "Alice Customer"
    fields.reporter.emailAddress = "alice@customer.example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "Bob Agent"
    fields.assignee.emailAddress = "bob@support.example.com"
    fields.summary = "Login broken"
    fields.updated = "2024-01-15T10:00:00+0000"
    fields.labels = []
    fields.priority = MagicMock(name="High")
    fields.status = MagicMock(name="Open")
    fields.resolution = None
    fields.issuetype = MagicMock(name="Service Request")
    fields.parent = None
    fields.project = MagicMock(key="SUP", name="Support Desk")
    fields.created = "2024-01-15T09:00:00+0000"
    fields.duedate = None
    fields.resolutiondate = None

    issue.fields = fields
    issue.key = "SUP-1"
    issue.raw = {"fields": {"description": "Customer cannot log in to the portal"}}
    return issue


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock._options = {"rest_api_version": "2"}
    mock.search_issues = MagicMock(return_value=[])
    mock.project = MagicMock()
    mock.projects = MagicMock(return_value=[])
    return mock


@pytest.fixture
def jsm_connector(mock_jira_client: MagicMock) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="SUP",
    )
    connector._jira_client = mock_jira_client
    return connector


@pytest.fixture
def jsm_connector_no_project(mock_jira_client: MagicMock) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )
    connector._jira_client = mock_jira_client
    return connector


# ---------------------------------------------------------------------------
# process_jira_issue: source parameter plumbing
# ---------------------------------------------------------------------------


class TestProcessJiraIssueSource:
    def test_defaults_to_jira_source(self, mock_issue: MagicMock) -> None:
        """Calling without explicit source emits plain Jira documents."""
        doc = process_jira_issue("https://example.atlassian.net", mock_issue)
        assert doc is not None
        assert doc.source == DocumentSource.JIRA

    def test_jsm_source_is_honoured(self, mock_issue: MagicMock) -> None:
        """Passing JSM source tags the document correctly."""
        doc = process_jira_issue(
            "https://example.atlassian.net",
            mock_issue,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )
        assert doc is not None
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_arbitrary_source_is_honoured(self, mock_issue: MagicMock) -> None:
        """The source parameter is forwarded verbatim — not hardcoded."""
        doc = process_jira_issue(
            "https://example.atlassian.net",
            mock_issue,
            source=DocumentSource.CONFLUENCE,  # deliberately odd, just testing passthrough
        )
        assert doc is not None
        assert doc.source == DocumentSource.CONFLUENCE

    def test_document_content_is_preserved(self, mock_issue: MagicMock) -> None:
        """Source change must not affect document content."""
        doc = process_jira_issue(
            "https://example.atlassian.net",
            mock_issue,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )
        assert doc is not None
        assert "SUP-1" in doc.semantic_identifier
        assert "Login broken" in doc.semantic_identifier
        assert len(doc.sections) == 1
        assert "Customer cannot log in" in doc.sections[0].text


# ---------------------------------------------------------------------------
# JiraServiceManagementConnector: subclass invariants
# ---------------------------------------------------------------------------


class TestJSMConnectorInvariants:
    def test_document_source_is_jsm(self) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
            project_key="SUP",
        )
        assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_is_subclass_of_jira_connector(self) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
        )
        assert isinstance(connector, JiraConnector)

    def test_source_cannot_be_overridden_by_caller(self) -> None:
        """Passing document_source=JIRA must still result in JSM source."""
        connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
            document_source=DocumentSource.JIRA,
        )
        assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_base_connector_defaults_to_jira(self) -> None:
        """Sanity check: plain JiraConnector still defaults to JIRA source."""
        connector = JiraConnector(jira_base_url="https://example.atlassian.net")
        assert connector.document_source == DocumentSource.JIRA

    def test_jsm_project_key_stored(self) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
            project_key="DESK",
        )
        assert connector.jira_project == "DESK"


# ---------------------------------------------------------------------------
# JQL generation
# ---------------------------------------------------------------------------


class TestJSMJQLGeneration:
    def test_with_project_key_uses_project_filter(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """When a project key is set, JQL scopes to that project."""
        jql = jsm_connector._get_jql_query(0, 9999999999)
        assert 'project = "SUP"' in jql
        # Should NOT add project type filter when a specific project is given
        assert "project type" not in jql

    def test_without_project_key_uses_project_type_filter(
        self, jsm_connector_no_project: JiraServiceManagementConnector
    ) -> None:
        """Without a project key, JQL filters by JSM project type."""
        jql = jsm_connector_no_project._get_jql_query(0, 9999999999)
        assert 'project type = "service_management"' in jql

    def test_time_window_always_present(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """Both start and end time constraints must appear in the JQL."""
        jql = jsm_connector._get_jql_query(0, 9999999999)
        assert "updated >=" in jql
        assert "updated <=" in jql

    def test_custom_jql_is_wrapped_and_time_added(
        self, mock_jira_client: MagicMock
    ) -> None:
        """User-supplied JQL is AND-ed with the time window, not the type filter."""
        connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
            jql_query='issuetype = "Service Request"',
        )
        connector._jira_client = mock_jira_client
        jql = connector._get_jql_query(0, 9999999999)
        # Custom JQL is in there
        assert 'issuetype = "Service Request"' in jql
        # Time window is applied
        assert "updated >=" in jql
        # The project-type guard is NOT added on top of custom JQL (user owns the filter)
        assert "project type" not in jql

    def test_jql_differs_from_base_connector_without_project(self) -> None:
        """JSM connector JQL must differ from plain Jira JQL when no project is set."""
        jira = JiraConnector(jira_base_url="https://example.atlassian.net")
        jsm = JiraServiceManagementConnector(jira_base_url="https://example.atlassian.net")
        jira_jql = jira._get_jql_query(0, 9999999999)
        jsm_jql = jsm._get_jql_query(0, 9999999999)
        assert jira_jql != jsm_jql
        assert "project type" in jsm_jql
        assert "project type" not in jira_jql


# ---------------------------------------------------------------------------
# validate_connector_settings
# ---------------------------------------------------------------------------


class TestJSMValidateConnectorSettings:
    def test_accepts_jsm_project(self, jsm_connector: JiraServiceManagementConnector) -> None:
        """Settings validation passes when the project is a JSM project."""
        project_mock = MagicMock()
        project_mock.projectTypeKey = "service_management"
        jsm_connector._jira_client.project.return_value = project_mock  # type: ignore[union-attr]

        # Should not raise
        jsm_connector.validate_connector_settings()

    def test_rejects_non_jsm_project(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """Settings validation must reject projects that are not JSM projects."""
        project_mock = MagicMock()
        project_mock.projectTypeKey = "software"
        jsm_connector._jira_client.project.return_value = project_mock  # type: ignore[union-attr]

        with pytest.raises(ConnectorValidationError) as exc_info:
            jsm_connector.validate_connector_settings()

        msg = str(exc_info.value)
        assert "service_management" in msg
        assert "SUP" in msg

    def test_no_project_key_skips_type_check(
        self, jsm_connector_no_project: JiraServiceManagementConnector
    ) -> None:
        """When no project key is configured, only the base validation runs."""
        # project() should never be called if no project key is set
        jsm_connector_no_project.validate_connector_settings()
        jsm_connector_no_project._jira_client.project.assert_not_called()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_jsm_source_is_registered(self) -> None:
        assert DocumentSource.JIRA_SERVICE_MANAGEMENT in CONNECTOR_CLASS_MAP

    def test_jsm_maps_to_jsm_connector_class(self) -> None:
        mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
        assert mapping.module_path == "onyx.connectors.jira.connector"
        assert mapping.class_name == "JiraServiceManagementConnector"

    def test_jira_mapping_unchanged(self) -> None:
        """Adding JSM must not accidentally break the plain Jira mapping."""
        mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA]
        assert mapping.class_name == "JiraConnector"
