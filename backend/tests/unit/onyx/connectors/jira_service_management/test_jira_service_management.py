"""Tests for the Jira Service Management connector.

Mirrors the mocking conventions used by the existing Jira connector test
suite (backend/tests/unit/onyx/connectors/jira/) — a MagicMock(spec=JIRA)
client injected directly as `_jira_client`, no live credentials needed.
Attribute access on the mock is narrowed with `cast(MagicMock, ...)`
rather than `# ty: ignore` comments, matching that suite's own convention.
"""

from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA, JIRAError
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
)
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


def _project_mock(connector: JiraServiceManagementConnector) -> MagicMock:
    jira_client = cast(JIRA, connector._jira_client)
    return cast(MagicMock, jira_client.project)


def _search_issues_mock(connector: JiraServiceManagementConnector) -> MagicMock:
    jira_client = cast(JIRA, connector._jira_client)
    return cast(MagicMock, jira_client.search_issues)


# --------------------------------------------------------------------------
# validate_connector_settings: the one genuinely JSM-specific check
# --------------------------------------------------------------------------


def test_validate_connector_settings_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    project = MagicMock()
    project.projectTypeKey = "service_desk"
    project_mock = _project_mock(jsm_connector)
    project_mock.return_value = project

    jsm_connector.validate_connector_settings()  # should not raise

    project_mock.assert_called_once_with("ITSM")


def test_validate_connector_settings_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    project = MagicMock()
    project.projectTypeKey = "software"
    _project_mock(jsm_connector).return_value = project

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

    cast(MagicMock, mock_jira_client.project).assert_not_called()


def test_validate_connector_settings_missing_project_type_key_is_permissive(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """If the Jira API response for some reason has no projectTypeKey at
    all, fail open rather than reject a possibly-valid project."""
    project = MagicMock()
    project.projectTypeKey = None
    _project_mock(jsm_connector).return_value = project

    jsm_connector.validate_connector_settings()  # should not raise


def test_validate_connector_settings_prioritizes_jql_over_project_type_check(
    jira_base_url: str, project_key: str, mock_jira_client: MagicMock
) -> None:
    """The constructor accepts jql_query alongside project_key even though
    the UI form never sets both. JiraConnector._get_jql_query gives
    jql_query absolute priority over jira_project for the actual fetch, so
    validation must match that precedence: skip the project-type check
    (which would validate a project the real query never touches) and
    validate the JQL instead, via the parent."""
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        jql_query="status = Open",
    )
    connector._jira_client = mock_jira_client
    _search_issues_mock(connector).return_value = []

    connector.validate_connector_settings()  # should not raise

    _search_issues_mock(connector).assert_called_once()
    _project_mock(connector).assert_not_called()


# --------------------------------------------------------------------------
# validate_connector_settings: credential and API-error paths
# --------------------------------------------------------------------------


def test_validate_connector_settings_raises_when_no_credentials(
    jira_base_url: str,
) -> None:
    """Calling validate_connector_settings() before load_credentials() must
    fail with the standard missing-credential error, not an AttributeError
    from calling .project() on a None client."""
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key="ITSM"
    )

    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status_code,expected_exception,expected_message",
    [
        (401, CredentialExpiredError, "Jira credential appears to be expired"),
        (403, InsufficientPermissionsError, "does not have sufficient permissions"),
        (429, ConnectorValidationError, "rate-limits being exceeded"),
        (404, UnexpectedValidationError, "Unexpected Jira error"),
    ],
)
def test_validate_connector_settings_propagates_project_lookup_errors(
    jsm_connector: JiraServiceManagementConnector,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """A real API error while fetching the project (not just a wrong
    project type) must surface as the same typed exception the base Jira
    connector uses — inherited error-handling shouldn't get bypassed by
    the single-call optimization in our override."""
    _project_mock(jsm_connector).side_effect = JIRAError(status_code=status_code)

    with pytest.raises(expected_exception) as excinfo:
        jsm_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


# --------------------------------------------------------------------------
# Document source re-tagging
# --------------------------------------------------------------------------


def test_load_from_checkpoint_retags_document_source(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    mock_issue = create_mock_issue()
    _search_issues_mock(jsm_connector).return_value = [mock_issue]

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
    _search_issues_mock(jsm_connector).return_value = [mock_issue]

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


def test_load_from_checkpoint_returns_valid_checkpoint_on_clean_run(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """On a clean run (no processing errors), the final returned checkpoint
    must be the same well-formed object the parent JiraConnector produced —
    re-tagging shouldn't disturb it — and no spurious ConnectorFailure
    should appear just because _retag ran over the stream.

    (Genuine failure pass-through — a ConnectorFailure surviving _retag
    untouched when the parent's processing actually errors — is exercised
    separately by test_load_from_checkpoint_yields_failure_untouched_on_processing_error;
    this test never triggers a failure, so it can't and doesn't stand in
    for that coverage.)"""
    mock_issue = create_mock_issue()
    _search_issues_mock(jsm_connector).return_value = [mock_issue]

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


# --------------------------------------------------------------------------
# Non-Document stream items and batch/error propagation
# --------------------------------------------------------------------------


def _drain(gen: Generator[Any, None, Any]) -> tuple[list[Any], Any]:
    """Runs a load_from_checkpoint generator to completion, returning every
    yielded item plus the final checkpoint from its return value."""
    items: list[Any] = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            return items, stop.value


def test_load_from_checkpoint_yields_hierarchy_node_untouched(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """load_everything_from_checkpoint_connector (used by the other tests)
    silently discards HierarchyNode items, so it can't prove _retag leaves
    them alone. Drain the raw generator directly instead — the project
    hierarchy node the parent yields ahead of the document must come
    through with its real project fields, not be dropped or mutated."""
    mock_issue = create_mock_issue()
    _search_issues_mock(jsm_connector).return_value = [mock_issue]

    checkpoint = jsm_connector.build_dummy_checkpoint()
    items, _ = _drain(jsm_connector.load_from_checkpoint(0, 10_000_000_000, checkpoint))

    hierarchy_nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert len(hierarchy_nodes) == 1
    assert hierarchy_nodes[0].raw_node_id == "ITSM"
    assert hierarchy_nodes[0].raw_parent_id is None


def test_load_from_checkpoint_yields_failure_untouched_on_processing_error(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """When the parent's per-issue processing genuinely raises (not just
    "no failures happened to occur" like the happy-path test covers), the
    resulting ConnectorFailure must reach the caller untouched — _retag's
    isinstance check must not accidentally swallow or reshape it."""
    mock_issue = create_mock_issue(key="ITSM-500")
    _search_issues_mock(jsm_connector).return_value = [mock_issue]

    checkpoint = jsm_connector.build_dummy_checkpoint()
    with patch(
        "onyx.connectors.jira.connector.process_jira_issue",
        side_effect=RuntimeError("boom"),
    ):
        items, _ = _drain(
            jsm_connector.load_from_checkpoint(0, 10_000_000_000, checkpoint)
        )

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == "ITSM-500"
    assert "boom" in failures[0].failure_message
    # The failure must not have been coerced into a fake Document.
    assert not any(isinstance(item, Document) for item in items)


def test_load_from_checkpoint_retags_every_document_in_a_batch(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """All existing tests use a single mock issue, which can't catch a bug
    where re-tagging only affects the first item in a page. Use three."""
    issues = [
        create_mock_issue(key="ITSM-1", summary="First"),
        create_mock_issue(key="ITSM-2", summary="Second"),
        create_mock_issue(key="ITSM-3", summary="Third"),
    ]
    _search_issues_mock(jsm_connector).return_value = issues

    outputs = load_everything_from_checkpoint_connector(
        jsm_connector, 0, 10_000_000_000
    )
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(documents) == 3
    assert {d.semantic_identifier.split(":")[0] for d in documents} == {
        "ITSM-1",
        "ITSM-2",
        "ITSM-3",
    }
    assert all(d.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for d in documents)


def test_load_from_checkpoint_propagates_search_error_instead_of_swallowing_it(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """If the underlying Jira search itself fails (not a per-issue
    processing error), that's a real validation/connectivity problem —
    the wrapping generator must let it propagate, not catch it as part of
    generic StopIteration handling and return an empty/silent result."""
    _search_issues_mock(jsm_connector).side_effect = JIRAError(status_code=401)

    checkpoint = jsm_connector.build_dummy_checkpoint()
    with pytest.raises(CredentialExpiredError):
        list(jsm_connector.load_from_checkpoint(0, 10_000_000_000, checkpoint))
