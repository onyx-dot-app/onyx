"""The Jira checks' row text and values, the merged rows, and the fixes the
design asked for: a missing email is blamed only for a refusal, and mapped
messages have one full stop."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.jira.capability_checks import (
    build_jira_doc_permission_sync_checks,
    build_jira_group_sync_checks,
    build_jira_indexing_checks,
)
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations

_CLOUD_URL = "https://example.atlassian.net"
_CLOUD_CREDENTIAL = {"jira_user_email": "bot@example.com", "jira_api_token": "t"}
_DC_CREDENTIAL = {"jira_api_token": "pat"}


def _gateway(*, is_cloud: bool = True) -> MagicMock:
    gateway: MagicMock = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = is_cloud
    gateway.get_myself.return_value = {"displayName": "Onyx Bot"}
    gateway.list_projects.return_value = [
        {"key": "AS", "name": "Onyx Support"},
        {"key": "ENG", "name": "Engineering"},
    ]
    gateway.get_project.return_value = {"key": "AS", "name": "Onyx Support"}
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = [
        {"id": "1", "fields": {"summary": "An issue", "project": {"key": "AS"}}}
    ]
    return gateway


def _run(
    check_id: str,
    gateway: MagicMock,
    credential_json: dict[str, Any] = _CLOUD_CREDENTIAL,
    **config: Any,
) -> CapabilityCheckResult:
    checks = [
        check for check in build_jira_indexing_checks() if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json=credential_json,
        connector_specific_config={"jira_base_url": _CLOUD_URL, **config},
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


def test_passing_checks_give_the_values_they_found() -> None:
    gateway = _gateway()

    assert _run("jira_auth", gateway).summary == "Signed in as Onyx Bot"
    assert _run("jira_projects_visible", gateway).summary == "2 projects visible"
    assert (
        _run("jira_configured_project", gateway, project_key="AS").summary
        == "Found project Onyx Support"
    )
    assert _run("jira_issue_read", gateway).summary == "Read an issue from AS"


@pytest.mark.parametrize("status", [429, 500])
def test_a_missing_email_is_not_blamed_for_a_rate_limit_or_a_server_error(
    status: int,
) -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_myself.side_effect = JiraApiError(
        f"HTTP {status}", status_code=status, body=None
    )

    result = _run("jira_auth", gateway, credential_json=_DC_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert "email" not in result.message


def test_a_refused_cloud_sign_in_without_an_email_names_the_email() -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_myself.side_effect = JiraApiError(
        "HTTP 401", status_code=401, body=None
    )

    result = _run("jira_auth", gateway, credential_json=_DC_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Account has no email for Jira Cloud"


def test_a_mapped_message_has_one_full_stop() -> None:
    gateway = _gateway()
    gateway.list_projects.side_effect = JiraApiError(
        "HTTP 403", status_code=403, body=None
    )

    result = _run("jira_projects_visible", gateway, scoped_token=True)

    assert ".." not in result.message
    assert ". (HTTP 403)" not in result.message
    assert result.summary == "Account cannot list projects"
    assert result.description == (
        "Jira refused the project list. (HTTP 403)\nRequired scope: read:jira-work"
    )


def test_variants_and_steps_share_a_row() -> None:
    checks = [
        *build_jira_indexing_checks(),
        *build_jira_doc_permission_sync_checks(),
        *build_jira_group_sync_checks(),
    ]
    rows: dict[str, set[str]] = {}
    for check in checks:
        rows.setdefault(check.row_id, set()).add(check.check_id)

    assert rows["jira_auth"] == {"jira_auth", "jira_scoped_token_auth"}
    assert rows["jira_group_listing"] == {
        "jira_group_listing",
        "jira_group_listing_complete",
    }
    # 14 checks on the 12 rows of the design.
    assert len(checks) == 14
    assert len(rows) == 12
    assert all(len(check.display_name) <= 24 for check in checks)
