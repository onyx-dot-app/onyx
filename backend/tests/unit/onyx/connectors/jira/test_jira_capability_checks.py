from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.jira.capability_checks import build_jira_indexing_checks
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations

_CLOUD_URL = "https://example.atlassian.net"
_DC_URL = "https://jira.example.com"
_CLOUD_CREDENTIAL = {"jira_user_email": "bot@example.com", "jira_api_token": "t"}
_DC_CREDENTIAL = {"jira_api_token": "pat"}
_ISSUE = {"id": "1", "key": "AS-1", "fields": {"summary": "An issue"}}


def _gateway(*, is_cloud: bool) -> MagicMock:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = is_cloud
    gateway.list_projects.return_value = [{"key": "AS", "name": "Onyx Support"}]
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = [_ISSUE]
    gateway.search_issues.return_value = [_ISSUE]
    return gateway


def _config(**overrides: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty tab fields."""
    return {
        "jira_base_url": _CLOUD_URL,
        "scoped_token": False,
        "project_key": "",
        "jql_query": "",
        **overrides,
    }


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    credential_json: dict[str, Any] | None = None,
) -> CapabilityCheckResult:
    checks = [
        check for check in build_jira_indexing_checks() if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json=credential_json or _CLOUD_CREDENTIAL,
        connector_specific_config=config if config is not None else _config(),
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


def _api_error(status: int, text: str | None = None) -> JiraApiError:
    return JiraApiError(f"HTTP {status}", status_code=status, text=text)


# --- jira_auth / jira_scoped_token_auth ---


def test_auth_passes() -> None:
    result = _run("jira_auth", _gateway(is_cloud=True))
    assert result.status == CapabilityCheckStatus.PASSED


def test_auth_check_matches_the_token_type() -> None:
    gateway = _gateway(is_cloud=True)
    assert not _run("jira_scoped_token_auth", gateway).applicable
    assert not _run("jira_auth", gateway, _config(scoped_token=True)).applicable


def test_auth_fails_for_a_rejected_token() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = _api_error(401)

    result = _run("jira_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "CredentialExpiredError"


def test_auth_fails_for_a_cloud_site_without_an_email() -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_myself.side_effect = _api_error(401)

    result = _run("jira_auth", gateway, credential_json=_DC_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "has no email" in result.message


def test_auth_fails_for_a_cloud_credential_on_data_center() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = _api_error(404)

    result = _run("jira_auth", gateway, _config(jira_base_url=_DC_URL))

    assert result.status == CapabilityCheckStatus.FAILED
    assert "leave the email empty" in result.message


def test_auth_fails_for_a_bad_data_center_token() -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_myself.side_effect = _api_error(401)

    result = _run(
        "jira_auth",
        gateway,
        _config(jira_base_url=_DC_URL),
        credential_json=_DC_CREDENTIAL,
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "CredentialExpiredError"


def test_scoped_auth_fails_for_a_site_that_is_not_cloud() -> None:
    response = requests.Response()
    response.status_code = 404
    response.url = f"{_DC_URL}/_edge/tenant_info"
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = requests.HTTPError(response=response)

    result = _run(
        "jira_scoped_token_auth",
        gateway,
        _config(jira_base_url=_DC_URL, scoped_token=True),
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "cloud id" in result.message


def test_scoped_auth_passes_without_the_user_scope() -> None:
    """``myself`` needs a user scope; a token with only read:jira-work still
    signs in and indexes."""
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = _api_error(
        401, '{"code":401,"message":"Unauthorized; scope does not match"}'
    )

    result = _run("jira_scoped_token_auth", gateway, _config(scoped_token=True))

    assert result.status == CapabilityCheckStatus.PASSED


def test_scoped_auth_fails_when_tenant_info_is_not_json() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", "<html>", 0
    )

    result = _run("jira_scoped_token_auth", gateway, _config(scoped_token=True))

    assert result.status == CapabilityCheckStatus.FAILED
    assert "cloud id" in result.message


def test_auth_is_indeterminate_when_the_site_is_unreachable() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.get_myself.side_effect = requests.ConnectionError("refused")

    result = _run("jira_auth", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE


# --- jira_projects_visible ---


def test_projects_visible_fails_without_projects() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.list_projects.return_value = []

    result = _run("jira_projects_visible", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Browse Projects" in result.message


def test_projects_visible_names_the_missing_scope() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.list_projects.side_effect = _api_error(
        401, '{"code":401,"message":"Unauthorized; scope does not match"}'
    )

    result = _run("jira_projects_visible", gateway, _config(scoped_token=True))

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "read:jira-work" in result.message


# --- jira_configured_project ---


def test_configured_project_applies_only_in_project_mode() -> None:
    gateway = _gateway(is_cloud=True)
    assert not _run("jira_configured_project", gateway).applicable
    assert not _run(
        "jira_configured_project",
        gateway,
        _config(project_key="AS", jql_query="project = AS"),
    ).applicable


def test_configured_project_passes() -> None:
    gateway = _gateway(is_cloud=True)

    result = _run("jira_configured_project", gateway, _config(project_key="AS"))

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_project.assert_called_once_with(project_key="AS")


def test_configured_project_suggests_the_key_for_a_name() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.get_project.side_effect = _api_error(404)

    result = _run(
        "jira_configured_project", gateway, _config(project_key="onyx support")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Did you mean the key `AS`?" in result.message


def test_configured_project_fails_for_a_key_with_spaces() -> None:
    result = _run(
        "jira_configured_project", _gateway(is_cloud=True), _config(project_key="AS ")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "spaces" in result.message


# --- jira_jql_query ---


@pytest.mark.parametrize("is_cloud", [True, False], ids=["cloud", "server"])
def test_jql_query_runs_the_indexing_query(is_cloud: bool) -> None:
    gateway = _gateway(is_cloud=is_cloud)

    result = _run("jira_jql_query", gateway, _config(jql_query='project = "AS"'))

    assert result.status == CapabilityCheckStatus.PASSED
    search = gateway.search_issue_ids if is_cloud else gateway.search_issues
    jql = search.call_args.kwargs["jql"]
    assert jql.startswith('(project = "AS") AND updated >= 0')


def test_jql_query_rejects_order_by_without_a_request() -> None:
    gateway = _gateway(is_cloud=True)

    result = _run(
        "jira_jql_query", gateway, _config(jql_query="project = AS ORDER BY created")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "ORDER BY" in result.message
    gateway.search_issue_ids.assert_not_called()


def test_jql_query_allows_order_by_inside_a_quoted_value() -> None:
    result = _run(
        "jira_jql_query",
        _gateway(is_cloud=True),
        _config(jql_query='summary ~ "order by"'),
    )

    assert result.status == CapabilityCheckStatus.PASSED


def test_jql_query_fails_with_the_jira_message() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.search_issue_ids.side_effect = _api_error(
        400,
        '{"errorMessages":["\'AS\' is a reserved JQL word. You must surround it '
        'in quotation marks."]}',
    )

    result = _run("jira_jql_query", gateway, _config(jql_query="project = AS"))

    assert result.status == CapabilityCheckStatus.FAILED
    assert "reserved JQL word" in result.message


def test_jql_query_is_indeterminate_when_it_matches_nothing() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token=None
    )

    result = _run("jira_jql_query", gateway, _config(jql_query="project = EMPTY"))

    assert result.status == CapabilityCheckStatus.INDETERMINATE


# --- jira_issue_read ---


def test_issue_read_reads_one_issue_on_cloud() -> None:
    gateway = _gateway(is_cloud=True)

    result = _run("jira_issue_read", gateway, _config(project_key="AS"))

    assert result.status == CapabilityCheckStatus.PASSED
    assert gateway.search_issue_ids.call_args.kwargs["max_results"] == 1
    gateway.bulk_fetch_issues.assert_called_once_with(issue_ids=["1"])
    gateway.search_issues.assert_not_called()


def test_issue_read_reads_one_issue_on_data_center() -> None:
    gateway = _gateway(is_cloud=False)

    result = _run(
        "jira_issue_read",
        gateway,
        _config(jira_base_url=_DC_URL),
        credential_json=_DC_CREDENTIAL,
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert gateway.search_issues.call_args.kwargs["max_results"] == 1
    gateway.search_issue_ids.assert_not_called()


def test_issue_read_fails_when_issues_come_without_fields() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.bulk_fetch_issues.return_value = []

    result = _run("jira_issue_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "fields" in result.message


def test_issue_read_fails_when_search_is_denied() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.search_issue_ids.side_effect = _api_error(403)

    result = _run("jira_issue_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"


def test_issue_read_leaves_a_bad_scope_to_the_scope_checks() -> None:
    gateway = _gateway(is_cloud=True)
    gateway.search_issue_ids.side_effect = _api_error(
        400, '{"errorMessages":["Error in the JQL Query"]}'
    )

    result = _run("jira_issue_read", gateway, _config(jql_query="project = ("))

    assert result.status == CapabilityCheckStatus.INDETERMINATE
