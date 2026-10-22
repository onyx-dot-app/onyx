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
    return JiraApiError(f"HTTP {status}", status_code=status, body=text)


def _advisories(result: CapabilityCheckResult) -> list[str]:
    return [advisory.message for advisory in result.advisories]


def test_all_checks_pass_on_a_readable_site() -> None:
    gateway = _gateway()
    for check in (
        build_jira_doc_permission_sync_checks() + build_jira_group_sync_checks()
    ):
        result = _run(check.check_id, gateway)
        assert result.status == CapabilityCheckStatus.PASSED, result
        assert _advisories(result) == [], result


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


@pytest.mark.parametrize(
    "check_id",
    [check.check_id for check in build_jira_doc_permission_sync_checks()],
)
def test_doc_perm_sync_checks_skip_when_the_jql_matches_nothing(
    check_id: str,
) -> None:
    gateway = _gateway()
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token=None
    )

    result = _run(
        check_id,
        gateway,
        {**_CONFIG, "project_key": "", "jql_query": 'project = "EMPTY"'},
    )

    # Nothing to check yet. The JQL check fails on its own row, and the
    # dependency rule stops these checks on a full run.
    assert result.status != CapabilityCheckStatus.PASSED
    assert "JQL query matched no issue" in result.message
    gateway.get_project_permission_scheme.assert_not_called()


def test_permission_scheme_read_is_incomplete_for_an_issue_without_project() -> None:
    gateway = _gateway()
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = []

    result = _run(
        "jira_permission_scheme_read",
        gateway,
        {**_CONFIG, "project_key": "", "jql_query": 'project = "AS"'},
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
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


def test_project_roles_read_skips_without_role_grants() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [_browse({"type": "group", "parameter": "devs"})]
    }

    result = _run("jira_project_roles_read", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.summary == "No role grants to test"
    gateway.get_project_role.assert_not_called()


def test_dependent_checks_defer_to_the_scheme_check() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.side_effect = _api_error(403)

    for check_id in (
        "jira_project_access_mappable",
        "jira_project_roles_read",
        "jira_permission_user_emails",
    ):
        assert _run(check_id, gateway).status == CapabilityCheckStatus.INCOMPLETE


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
def test_permission_user_emails_skips_public_or_group_grants(
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

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable
    gateway.get_user.assert_not_called()


def test_permission_user_emails_skips_when_a_role_holds_a_group() -> None:
    gateway = _gateway()
    gateway.get_project_role.return_value = {
        "actors": [
            {"actorGroup": {"name": "devs"}},
            {"actorUser": {"accountId": "acc-1"}},
        ]
    }
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.summary == "Access comes through groups"


def test_permission_user_emails_skips_app_accounts() -> None:
    gateway = _gateway()
    gateway.get_project_role.return_value = {
        "actors": [
            {"actorUser": {"accountId": "app-1"}},
            {"actorUser": {"accountId": "acc-1"}},
        ]
    }
    gateway.get_user.side_effect = [
        {"accountType": "app"},
        {"accountType": "atlassian", "emailAddress": "dev@example.com"},
    ]

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.PASSED


@pytest.mark.parametrize(
    "permissions,actors",
    [
        ([_browse({"type": "projectRole", "value": "10003"})], []),
        (
            [_browse({"type": "projectRole", "value": "10003"})],
            [{"actorUser": {"accountId": "app-1"}}],
        ),
        ([_browse({"type": "reporter"})], []),
    ],
    ids=["empty-role", "app-only-role", "reporter-only"],
)
def test_permission_user_emails_fails_when_no_user_would_get_access(
    permissions: list[dict[str, Any]], actors: list[dict[str, Any]]
) -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {"permissions": permissions}
    gateway.get_project_role.return_value = {"actors": actors}
    gateway.get_user.return_value = {"accountType": "app"}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "ConnectorValidationError"
    assert "no user would get access" in result.message


def test_permission_user_emails_is_incomplete_for_partial_app_sample() -> None:
    gateway = _gateway()
    gateway.get_project_role.return_value = {
        "actors": [{"actorUser": {"accountId": f"app-{i}"}} for i in range(6)]
    }
    gateway.get_user.return_value = {"accountType": "app"}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE


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


@pytest.mark.parametrize(
    "email,status",
    [
        ("", CapabilityCheckStatus.FAILED),
        ("dev@example.com", CapabilityCheckStatus.PASSED),
    ],
    ids=["hidden", "visible"],
)
def test_full_run_checks_direct_user_emails_without_role_grants(
    email: str, status: CapabilityCheckStatus
) -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [
            _browse({"type": "user", "value": "acc-2", "user": {"emailAddress": email}})
        ]
    }
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = [{"id": "1", "key": "AS-1", "fields": {}}]
    context = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json={"jira_user_email": "bot@example.com", "jira_api_token": "t"},
        connector_specific_config=_CONFIG,
        access_type=AccessType.SYNC,
        source_operations=gateway,
    )

    checks = (
        build_jira_indexing_checks()
        + build_jira_doc_permission_sync_checks()
        + build_jira_group_sync_checks()
    )

    results = run_capability_checks(checks, context)

    by_id = {result.check_id: result for result in results}
    assert by_id["jira_project_roles_read"].status == CapabilityCheckStatus.SKIPPED
    assert by_id["jira_permission_user_emails"].status == status


def test_permission_user_emails_is_incomplete_for_a_partial_sample() -> None:
    """Sync reads every role user; hidden emails in a sample prove nothing."""
    gateway = _gateway()
    gateway.get_project_role.return_value = {
        "actors": [{"actorUser": {"accountId": f"acc-{i}"}} for i in range(6)]
    }
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE


def test_permission_user_emails_reads_every_role_up_to_the_sample() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [
            _browse({"type": "projectRole", "value": str(role_id)})
            for role_id in range(4)
        ]
    }
    gateway.get_user.return_value = {"accountType": "atlassian", "emailAddress": ""}

    result = _run("jira_permission_user_emails", gateway)

    assert gateway.get_project_role.call_count == 3
    assert result.status == CapabilityCheckStatus.INCOMPLETE


def test_project_roles_read_skips_public_projects() -> None:
    gateway = _gateway()
    gateway.get_project_permission_scheme.return_value = {
        "permissions": [
            _browse({"type": "applicationRole"}),
            _browse({"type": "projectRole", "value": "10003"}),
        ]
    }
    gateway.get_project_role.side_effect = _api_error(403)

    result = _run("jira_project_roles_read", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.summary == "AS is open to all users"
    gateway.get_project_role.assert_not_called()


# --- sampling several projects ---

_ALL_PROJECTS = {**_CONFIG, "project_key": ""}
_OPEN_SCHEME = {"permissions": [_browse({"type": "applicationRole"})]}
_GROUP_SCHEME = {"permissions": [_browse({"type": "group", "parameter": "devs"})]}
_ROLE_SCHEME = {"permissions": [_browse({"type": "projectRole", "value": "10003"})]}
_SAMPLE_CHECK_IDS = ["jira_project_roles_read", "jira_permission_user_emails"]


def _schemes_by_project(gateway: MagicMock, schemes: dict[str, dict[str, Any]]) -> None:
    gateway.list_projects.return_value = [{"key": key} for key in schemes]

    def _scheme(*, project_key: str, **_: bool) -> dict[str, Any]:
        return schemes[project_key]

    gateway.get_project_permission_scheme.side_effect = _scheme


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_move_past_an_open_project(check_id: str) -> None:
    gateway = _gateway()
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "ROLE": _ROLE_SCHEME})

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.PASSED, result
    gateway.get_project_role.assert_called_with(project_key="ROLE", role_id="10003")


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_move_past_an_open_project_of_a_jql_scope(
    check_id: str,
) -> None:
    gateway = _gateway()
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "ROLE": _ROLE_SCHEME})
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1", "2", "3"], next_page_token=None
    )
    gateway.bulk_fetch_issues.return_value = [
        {"fields": {"project": {"key": key}}} for key in ("OPEN", "OPEN", "ROLE")
    ]

    result = _run(check_id, gateway, {**_ALL_PROJECTS, "jql_query": "type = Bug"})

    assert result.status == CapabilityCheckStatus.PASSED, result
    assert gateway.get_project_permission_scheme.call_count == 2


def _jql_issues(*project_keys: str) -> list[dict[str, Any]]:
    return [{"fields": {"project": {"key": key}}} for key in project_keys]


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_are_incomplete_when_the_jql_matches_more_cloud_issues(
    check_id: str,
) -> None:
    gateway = _gateway()
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "TEAM": _GROUP_SCHEME})
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1", "2"], next_page_token="next"
    )
    gateway.bulk_fetch_issues.return_value = _jql_issues("OPEN", "TEAM")

    result = _run(check_id, gateway, {**_ALL_PROJECTS, "jql_query": "type = Bug"})

    assert result.status == CapabilityCheckStatus.INCOMPLETE, result
    assert result.description is not None
    assert result.description.startswith(
        "Checked 2 projects, and the JQL query matches more"
    )


@pytest.mark.parametrize(
    ("next_offset_issues", "expected"),
    [
        ([], CapabilityCheckStatus.SKIPPED),
        # Jira returned a short page, but more issues match.
        (_jql_issues("ROLE"), CapabilityCheckStatus.INCOMPLETE),
    ],
)
@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_of_a_data_center_jql_scope(
    check_id: str,
    next_offset_issues: list[dict[str, Any]],
    expected: CapabilityCheckStatus,
) -> None:
    gateway = _gateway(is_cloud=False)
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "TEAM": _GROUP_SCHEME})
    pages: list[list[dict[str, Any]]] = [
        _jql_issues("OPEN", "TEAM"),
        next_offset_issues,
    ]
    gateway.search_issues.side_effect = pages

    result = _run(check_id, gateway, {**_ALL_PROJECTS, "jql_query": "type = Bug"})

    assert result.status == expected, result
    assert gateway.search_issues.call_args.kwargs["start_at"] == 2


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_are_incomplete_when_more_projects_exist(
    check_id: str,
) -> None:
    gateway = _gateway()
    _schemes_by_project(
        gateway,
        {
            f"P{index}": _OPEN_SCHEME if index % 2 else _GROUP_SCHEME
            for index in range(8)
        },
    )

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.INCOMPLETE, result
    assert result.description is not None
    assert result.description.startswith("Checked 5 of 8 projects")
    assert gateway.get_project_permission_scheme.call_count == 5


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_skip_when_every_project_was_read(check_id: str) -> None:
    gateway = _gateway()
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "TEAM": _GROUP_SCHEME})

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.SKIPPED, result


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_leave_out_an_unreadable_later_project(check_id: str) -> None:
    gateway = _gateway()
    _schemes_by_project(
        gateway, {"OPEN": _OPEN_SCHEME, "HIDDEN": {}, "ROLE": _ROLE_SCHEME}
    )
    schemes_or_errors: list[dict[str, Any] | JiraApiError] = [
        _OPEN_SCHEME,
        _api_error(403),
        _ROLE_SCHEME,
    ]
    gateway.get_project_permission_scheme.side_effect = schemes_or_errors

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.PASSED, result


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_are_incomplete_when_a_project_cannot_be_read(
    check_id: str,
) -> None:
    gateway = _gateway()
    _schemes_by_project(gateway, {"OPEN": _OPEN_SCHEME, "HIDDEN": {}})
    schemes_or_errors: list[dict[str, Any] | JiraApiError] = [
        _OPEN_SCHEME,
        _api_error(403),
    ]
    gateway.get_project_permission_scheme.side_effect = schemes_or_errors

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.INCOMPLETE, result
    assert result.description is not None
    assert result.description.startswith(
        "Checked 1 of 2 projects (1 more could not be read)"
    )


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_stop_when_jira_rate_limits_a_later_project(
    check_id: str,
) -> None:
    gateway = _gateway()
    _schemes_by_project(
        gateway, {"OPEN": _OPEN_SCHEME, "BUSY": {}, "ROLE": _ROLE_SCHEME}
    )
    schemes_or_errors: list[dict[str, Any] | JiraApiError] = [
        _OPEN_SCHEME,
        _api_error(429),
        _ROLE_SCHEME,
    ]
    gateway.get_project_permission_scheme.side_effect = schemes_or_errors

    result = _run(check_id, gateway, _ALL_PROJECTS)

    assert result.status == CapabilityCheckStatus.INCOMPLETE, result
    assert result.summary == "Rate limited by Jira"
    assert gateway.get_project_permission_scheme.call_count == 2


@pytest.mark.parametrize("check_id", _SAMPLE_CHECK_IDS)
def test_sampled_checks_skip_an_open_configured_project(check_id: str) -> None:
    gateway = _gateway()
    gateway.list_projects.return_value = [{"key": "OTHER"}]
    gateway.get_project_permission_scheme.return_value = _OPEN_SCHEME

    result = _run(check_id, gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED, result
    assert result.summary == "AS is open to all users"
    gateway.get_project_permission_scheme.assert_called_once_with(project_key="AS")


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
    assert result.summary == "Read 1 members in 1 groups"


def test_group_membership_is_incomplete_for_empty_groups() -> None:
    gateway = _gateway()
    gateway.get_group_members_page.return_value = {"values": [], "isLast": True}

    result = _run("jira_group_membership", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No members found to test"


def test_group_member_emails_is_incomplete_without_user_members() -> None:
    gateway = _gateway()
    gateway.get_group_members_page.return_value = {
        "values": [{"accountType": "app", "displayName": "Automation"}],
        "isLast": True,
    }

    result = _run("jira_group_member_emails", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No user members found to test"


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


@pytest.mark.parametrize(
    "group_names,is_last",
    [(["devs"], False), (["a", "b", "c", "d"], True)],
    ids=["more-pages", "more-groups"],
)
def test_group_member_emails_is_incomplete_for_a_partial_sample(
    group_names: list[str], is_last: bool
) -> None:
    gateway = _gateway(is_cloud=False)
    gateway.list_groups.return_value = JiraGroupPage(
        group_names=group_names, total=len(group_names)
    )
    gateway.get_group_members_page.return_value = {
        "values": [{"name": "jdoe"}],
        "isLast": is_last,
    }

    result = _run("jira_group_member_emails", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
