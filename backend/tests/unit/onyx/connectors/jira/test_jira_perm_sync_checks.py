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
)
from onyx.connectors.jira.models import JiraGroupPage, JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.db.enums import AccessType

_CONFIG = {
    "jira_base_url": "https://example.atlassian.net",
    "scoped_token": False,
    "project_key": "AS",
    "jql_query": "",
}
_SCOPE_MISMATCH = '{"code":401,"message":"Unauthorized; scope does not match"}'


def _browse(holder: dict[str, Any]) -> dict[str, Any]:
    return {"id": 1, "permission": "BROWSE_PROJECTS", "holder": holder}


def _gateway(*, is_cloud: bool = True) -> MagicMock:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = is_cloud
    gateway.list_projects.return_value = [{"key": "AS"}]
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [_browse({"type": "projectRole", "value": "10003"})]
    }
    gateway.get_project_role.return_value = {
        "actors": [{"actorUser": {"accountId": "acc-1"}}]
    }
    gateway.get_user.return_value = {
        "accountType": "atlassian",
        "emailAddress": "dev@example.com",
    }
    gateway.list_groups.return_value = JiraGroupPage(group_names=["devs"], total=1)
    gateway.get_group_members_page.return_value = {
        "values": [{"accountType": "atlassian", "emailAddress": "dev@example.com"}],
        "isLast": True,
    }
    return gateway


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    access_type: AccessType = AccessType.SYNC,
) -> CapabilityCheckResult:
    checks = [
        check
        for check in build_jira_doc_permission_sync_checks()
        + build_jira_group_sync_checks()
        if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json={"jira_user_email": "bot@example.com", "jira_api_token": "t"},
        connector_specific_config=config or _CONFIG,
        access_type=access_type,
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


def _api_error(status: int, text: str | None = None) -> JiraApiError:
    return JiraApiError(f"HTTP {status}", status_code=status, text=text)


def test_all_checks_pass_on_a_readable_site() -> None:
    gateway = _gateway()
    for check in (
        build_jira_doc_permission_sync_checks() + build_jira_group_sync_checks()
    ):
        result = _run(check.check_id, gateway)
        assert result.status == CapabilityCheckStatus.PASSED, result


def test_perm_sync_checks_do_not_apply_to_public_connectors() -> None:
    result = _run(
        "jira_permission_scheme_read", _gateway(), access_type=AccessType.PUBLIC
    )
    assert not result.applicable


# --- jira_permission_scheme_read ---


def test_permission_scheme_read_fails_without_admin_access() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.side_effect = _api_error(403)

    result = _run("jira_permission_scheme_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Administer Jira" in result.message


def test_permission_scheme_read_names_scopes_for_a_scoped_token() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.side_effect = _api_error(401, _SCOPE_MISMATCH)

    result = _run(
        "jira_permission_scheme_read", gateway, {**_CONFIG, "scoped_token": True}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "manage:jira-configuration" in result.message


def test_permission_scheme_read_probes_the_first_project_without_a_project() -> None:
    gateway = _gateway()

    _run("jira_permission_scheme_read", gateway, {**_CONFIG, "project_key": ""})

    gateway.get_project_permission_scheme.assert_called_once_with(project_key="AS")


def test_permission_scheme_read_probes_the_project_of_a_jql_match() -> None:
    gateway = _gateway()
    gateway.list_projects.return_value = [{"key": "OTHER"}]
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = [
        {"key": "AS-1", "fields": {"project": {"key": "AS"}}}
    ]

    _run(
        "jira_permission_scheme_read",
        gateway,
        {**_CONFIG, "project_key": "", "jql_query": 'project = "AS"'},
    )

    gateway.get_project_permission_scheme.assert_called_once_with(project_key="AS")


def test_permission_scheme_read_is_indeterminate_when_the_jql_matches_nothing() -> None:
    gateway = _gateway()
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token=None
    )

    result = _run(
        "jira_permission_scheme_read",
        gateway,
        {**_CONFIG, "project_key": "", "jql_query": 'project = "EMPTY"'},
    )

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    gateway.get_project_permission_scheme.assert_not_called()


def test_permission_scheme_read_fails_for_a_scheme_without_grants() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {"id": 1}

    result = _run("jira_permission_scheme_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED


# --- jira_project_access_mappable ---


def test_project_access_mappable_warns_on_dynamic_grants() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [_browse({"type": "reporter"}), _browse({"type": "assignee"})]
    }

    result = _run("jira_project_access_mappable", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert not result.required
    assert "assignee, reporter" in result.message


# --- jira_project_roles_read ---


def test_project_roles_read_fails_when_roles_are_hidden() -> None:
    gateway = _gateway()
    gateway.get_project_role.side_effect = _api_error(403)

    result = _run("jira_project_roles_read", gateway)

    assert result.status == CapabilityCheckStatus.FAILED


def test_project_roles_read_passes_without_role_grants() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [_browse({"type": "group", "parameter": "devs"})]
    }

    result = _run("jira_project_roles_read", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_project_role.assert_not_called()


def test_dependent_checks_defer_to_the_scheme_check() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.side_effect = _api_error(403)

    for check_id in (
        "jira_project_access_mappable",
        "jira_project_roles_read",
        "jira_permission_user_emails",
    ):
        assert _run(check_id, gateway).status == CapabilityCheckStatus.INDETERMINATE


# --- jira_permission_user_emails ---


def test_permission_user_emails_fails_when_emails_are_hidden() -> None:
    gateway = _gateway()
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Profile and visibility" in result.message


@pytest.mark.parametrize(
    "extra_holder",
    [
        {"type": "applicationRole"},
        {"type": "anyone"},
        {"type": "group", "parameter": "devs"},
    ],
    ids=["application-role", "anyone", "group"],
)
def test_permission_user_emails_passes_for_public_or_group_grants(
    extra_holder: dict[str, Any],
) -> None:
    """Public grants sync without reading users; group grants give access
    through group sync. Hidden user emails must not block either."""
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [
            _browse({"type": "projectRole", "value": "10003"}),
            _browse(extra_holder),
        ]
    }
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_user.assert_not_called()


def test_permission_user_emails_passes_when_a_role_holds_a_group() -> None:
    gateway = _gateway()
    gateway.get_project_role.return_value = {
        "actors": [
            {"actorGroup": {"name": "devs"}},
            {"actorUser": {"accountId": "acc-1"}},
        ]
    }
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.PASSED


def test_permission_user_emails_skips_app_accounts() -> None:
    gateway = _gateway()
    gateway.get_user.return_value = {"accountType": "app"}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.PASSED


def test_permission_user_emails_looks_up_data_center_users_by_name() -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_project_role.return_value = {
        "actors": [{"type": "atlassian-user-role-actor", "name": "jdoe"}]
    }

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_user.assert_called_once_with(user_id="jdoe")


def test_permission_user_emails_reads_direct_user_grants() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [
            _browse({"type": "user", "value": "acc-2", "user": {"emailAddress": ""}})
        ]
    }

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    gateway.get_user.assert_not_called()


# --- group sync ---


def test_group_listing_fails_when_empty() -> None:
    gateway = _gateway()
    gateway.list_groups.return_value = JiraGroupPage(group_names=[], total=0)

    result = _run("jira_group_listing", gateway)

    assert result.status == CapabilityCheckStatus.FAILED


def test_group_listing_complete_warns_on_a_truncated_listing() -> None:
    gateway = _gateway()
    gateway.list_groups.return_value = JiraGroupPage(group_names=["a", "b"], total=5)

    result = _run("jira_group_listing_complete", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert not result.required
    assert "misses 3 groups" in result.message


def test_group_membership_fails_for_a_scoped_token_without_the_scope() -> None:
    gateway = _gateway()
    gateway.get_group_members_page.side_effect = _api_error(401, _SCOPE_MISMATCH)

    result = _run("jira_group_membership", gateway, {**_CONFIG, "scoped_token": True})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "read:jira-user" in result.message


def test_group_membership_skips_a_deleted_group() -> None:
    gateway = _gateway()
    gateway.list_groups.return_value = JiraGroupPage(
        group_names=["gone", "devs"], total=2
    )
    gateway.get_group_members_page.side_effect = [
        _api_error(
            404, '{"errorMessages":["The group named \'gone\' does not exist"]}'
        ),
        {"values": [{"emailAddress": "dev@example.com"}]},
    ]

    result = _run("jira_group_membership", gateway)

    assert result.status == CapabilityCheckStatus.PASSED


def test_group_membership_fails_without_the_group_member_api() -> None:
    gateway = _gateway()
    gateway.get_group_members_page.side_effect = _api_error(404, "Not Found")

    result = _run("jira_group_membership", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Jira 6.0+" in result.message


def test_group_member_emails_fails_when_emails_are_hidden() -> None:
    gateway = _gateway(is_cloud=False)
    gateway.get_group_members_page.return_value = {"values": [{"name": "jdoe"}]}

    result = _run("jira_group_member_emails", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "User email visibility" in result.message
