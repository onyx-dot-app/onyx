"""Unit tests for the Jira Service Management connector.

These tests exercise the logic that is specific to JSM (source stamping,
service-desk project discovery, and JQL scoping) with a mocked Jira source-operations gateway, so
they run in CI without a live Jira instance or credentials.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    DocumentFailure,
)

BASE_URL = "https://danswerai.atlassian.net"

# Fixed window so the epoch-ms bounds in the asserted JQL are deterministic.
START = 1_000_000.0
END = 2_000_000.0
TIME_JQL = "updated >= 1000000000 AND updated <= 2000000000"


def _project(key: str, project_type: str) -> dict[str, Any]:
    return {"key": key, "projectTypeKey": project_type}


def _connector(
    project_key: str | None = None,
    jql_query: str | None = None,
) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(
        jira_base_url=BASE_URL, project_key=project_key, jql_query=jql_query
    )


def test_document_source_is_jira_service_management() -> None:
    connector = _connector()
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_service_desk_project_keys_filters_by_type_and_caches() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        _project("SUP", "service_desk"),
        _project("ENG", "software"),
        _project("OPS", "service_desk"),
        _project("BIZ", "business"),
    ]
    connector._source_operations = mock_ops

    keys = connector._get_service_desk_project_keys()
    assert keys == ["SUP", "OPS"]

    # Second call should hit the cache, not re-list projects.
    keys_again = connector._get_service_desk_project_keys()
    assert keys_again == ["SUP", "OPS"]
    mock_ops.list_projects.assert_called_once()


def test_jql_uses_custom_query_verbatim() -> None:
    connector = _connector(jql_query="project = 'SUP' AND issuetype = Incident")
    jql = connector._get_jql_query(START, END)
    assert jql == f"(project = 'SUP' AND issuetype = Incident) AND {TIME_JQL}"


def test_jql_scopes_to_explicit_project_key() -> None:
    connector = _connector(project_key="SUP")
    jql = connector._get_jql_query(START, END)
    assert jql == f'project = "SUP" AND {TIME_JQL}'


def test_jql_auto_scopes_to_service_desk_projects() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        _project("SUP", "service_desk"),
        _project("ENG", "software"),
        _project("OPS", "service_desk"),
    ]
    connector._source_operations = mock_ops

    jql = connector._get_jql_query(START, END)
    assert jql == f'project in ("SUP", "OPS") AND {TIME_JQL}'


def test_jql_raises_when_no_service_desk_projects() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [
        _project("ENG", "software"),
        _project("BIZ", "business"),
    ]
    connector._source_operations = mock_ops

    with pytest.raises(ConnectorValidationError):
        connector._get_jql_query(START, END)


def test_projects_without_type_key_are_ignored() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    # A raw project missing projectTypeKey must not crash discovery.
    mock_ops.list_projects.return_value = [
        {"key": "LEGACY"},
        _project("SUP", "service_desk"),
    ]
    connector._source_operations = mock_ops

    assert connector._get_service_desk_project_keys() == ["SUP"]


def test_validate_raises_when_no_service_desk_projects() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [_project("ENG", "software")]
    connector._source_operations = mock_ops

    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()


def test_validate_passes_with_a_service_desk_project() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [_project("SUP", "service_desk")]
    connector._source_operations = mock_ops

    # Should not raise.
    connector.validate_connector_settings()


def test_validate_with_explicit_project_skips_service_desk_check() -> None:
    # An explicit project key means auto-scoping is not used, so the absence of
    # service desk projects must not fail validation.
    connector = _connector(project_key="SUP")
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [_project("ENG", "software")]
    connector._source_operations = mock_ops

    # Should not raise.
    connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status_code, expected_error, match",
    [
        (401, CredentialExpiredError, "HTTP 401"),
        (403, InsufficientPermissionsError, "HTTP 403"),
        (429, ConnectorValidationError, "rate-limits"),
    ],
)
def test_validate_maps_jira_errors_when_auto_scoping(
    status_code: int, expected_error: type[Exception], match: str
) -> None:
    # The auto-scope path skips the base validator's list_projects() probe, so it
    # must still map Jira HTTP errors to the same typed errors as the base.
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.side_effect = JiraApiError(
        "err", status_code=status_code, body="err"
    )
    connector._source_operations = mock_ops

    with pytest.raises(expected_error, match=match):
        connector.validate_connector_settings()


def test_validate_without_credentials_raises_missing_credential() -> None:
    connector = _connector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status_code, expected_error",
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
    ],
)
def test_jql_maps_dead_credentials_when_auto_scoping(
    status_code: int, expected_error: type[Exception]
) -> None:
    # Discovery runs before the first search, so without this mapping a revoked
    # credential would never mark an auto-scoped connector invalid.
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.side_effect = JiraApiError(
        "err", status_code=status_code, body="err"
    )
    connector._source_operations = mock_ops

    with pytest.raises(expected_error):
        connector._get_jql_query(START, END)


@pytest.mark.parametrize("status_code", [429, 500])
def test_jql_keeps_transient_errors_out_of_validation_errors(status_code: int) -> None:
    # Validation errors count towards marking the connector invalid, which a
    # passing rate limit or server error must not do.
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.side_effect = JiraApiError(
        "err", status_code=status_code, body="err"
    )
    connector._source_operations = mock_ops

    with pytest.raises(JiraApiError):
        connector._get_jql_query(START, END)


def _failed_issue(issue_key: str) -> ConnectorFailure:
    doc_id = f"{BASE_URL}/browse/{issue_key}"
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=doc_id, document_link=doc_id),
        failure_message="synthetic",
    )


def test_reindex_stays_in_service_desk_scope() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.return_value = [_project("HELP", "service_desk")]
    connector._source_operations = mock_ops

    with patch.object(
        connector, "_search_all_issues", return_value=iter([])
    ) as mock_search:
        results = list(connector.reindex([_failed_issue("ENG-1")]))

    mock_search.assert_called_once_with('project in ("HELP") AND key in ("ENG-1")')
    assert len(results) == 1
    assert isinstance(results[0], ConnectorFailure)
    assert "ENG-1" in results[0].failure_message


def test_reindex_with_explicit_project_skips_discovery() -> None:
    connector = _connector(project_key="HELP")
    mock_ops = MagicMock()
    connector._source_operations = mock_ops

    with patch.object(
        connector, "_search_all_issues", return_value=iter([])
    ) as mock_search:
        list(connector.reindex([_failed_issue("HELP-1")]))

    mock_search.assert_called_once_with('project = "HELP" AND key in ("HELP-1")')
    mock_ops.list_projects.assert_not_called()


def test_reindex_fails_the_run_on_dead_credentials() -> None:
    connector = _connector()
    mock_ops = MagicMock()
    mock_ops.list_projects.side_effect = JiraApiError(
        "err", status_code=401, body="err"
    )
    connector._source_operations = mock_ops

    with pytest.raises(CredentialExpiredError):
        list(connector.reindex([_failed_issue("HELP-1")]))
