"""The Linear checks' rows: the design's short lines and descriptions, the
form-run sign-in policy, the rate-limit stop, the run order, the partial Find
of selected teams and projects, Error Details, and what a check that tested
nothing says."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from ee.onyx.external_permissions.linear.capability_checks import (
    build_linear_doc_permission_sync_checks,
    build_linear_group_sync_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.linear.capability_checks import build_linear_indexing_checks
from onyx.connectors.linear.models import (
    IssueAccess,
    IssueAccessPage,
    IssueShare,
    LinearProject,
    LinearTeam,
    LinearUser,
    LinearViewer,
    WorkspaceUsers,
)
from onyx.connectors.linear.source_operations import (
    LinearApiError,
    LinearAuthError,
    LinearGraphQLError,
    LinearPagingError,
    LinearRateLimitError,
    LinearSourceOperations,
    LinearTokenLockError,
    LinearTokenRefreshError,
    LinearUnreachableError,
)
from onyx.connectors.models import ConnectorMissingCredentialError

_API_KEY_CREDENTIAL: dict[str, Any] = {"linear_api_key": "lin_api_x"}
_OAUTH_CREDENTIAL: dict[str, Any] = {"access_token": "t", "refresh_token": "r"}
_TEAM = LinearTeam(id="t1", key="ENG", visibility="public")


def _all_checks() -> list[CapabilityCheck]:
    return [
        *build_linear_indexing_checks(),
        *build_linear_doc_permission_sync_checks(),
        *build_linear_group_sync_checks(),
    ]


def _gateway() -> MagicMock:
    gateway = create_autospec(LinearSourceOperations, instance=True)
    gateway.get_viewer.return_value = LinearViewer(email="ada@x.com", guest=False)
    gateway.list_team_keys.return_value = {"ENG"}
    gateway.list_projects.return_value = [LinearProject(name="Roadmap", slug_id="abc")]
    gateway.iterate_issues.side_effect = lambda **_: iter([[{"identifier": "ENG-1"}]])
    gateway.iterate_issue_access.side_effect = lambda **_: iter(
        [
            IssueAccessPage(
                organization_id="o",
                issues=[
                    IssueAccess(
                        id="i1",
                        team=_TEAM,
                        share=IssueShare(parent_id=None, inherits=False, emails=set()),
                    )
                ],
            )
        ]
    )
    gateway.list_workspace_users.return_value = WorkspaceUsers(
        organization_id="o",
        user_count=2,
        users=[
            LinearUser(email=f"{name}@x.com", active=True, guest=False, app=False)
            for name in ("ada", "bob")
        ],
    )
    gateway.list_teams.return_value = [_TEAM]
    gateway.list_team_members.return_value = [
        LinearUser(email="ada@x.com", active=True, guest=False, app=False)
    ]
    return gateway


def _run_all(
    check_ids: list[str],
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    *,
    credential: dict[str, Any] = _API_KEY_CREDENTIAL,
    form_run: bool = False,
) -> dict[str, CapabilityCheckResult]:
    checks: list[CapabilityCheck] = [
        check for check in _all_checks() if check.check_id in check_ids
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.LINEAR,
        credential_json=credential,
        connector_specific_config=config if config is not None else {},
        source_operations=gateway,
    )
    return {
        result.check_id: result
        for result in run_capability_checks(checks, context, form_run=form_run)
    }


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    *,
    credential: dict[str, Any] = _API_KEY_CREDENTIAL,
    form_run: bool = False,
) -> CapabilityCheckResult:
    return _run_all(
        [check_id], gateway, config, credential=credential, form_run=form_run
    )[check_id]


# --- Sign in to Linear ---


def test_sign_in_names_the_user() -> None:
    result = _run("linear_token", _gateway())

    assert result.display_name == "Sign in to Linear"
    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Signed in as ada@x.com"


def test_a_rejected_key_names_a_new_key_and_oauth_names_reconnect() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearAuthError(
        "refused", status_code=401, body="refused"
    )

    api_key = _run("linear_token", gateway)
    oauth = _run("linear_token", gateway, credential=_OAUTH_CREDENTIAL)

    assert api_key.status == CapabilityCheckStatus.FAILED
    assert api_key.error_kind == CheckErrorKind.REJECTED
    assert api_key.summary == oauth.summary == "Linear rejected the credential"
    assert api_key.description is not None and "personal API key" in (
        api_key.description
    )
    assert oauth.description is not None and oauth.description.endswith(
        "Reconnect the account through Linear."
    )


def test_a_refused_renewal_is_an_expired_sign_in() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearTokenRefreshError(
        "invalid_grant", status_code=400, body="invalid_grant"
    )

    result = _run("linear_token", gateway, credential=_OAUTH_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Linear sign-in expired"


def test_a_missing_credential_says_so() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = ConnectorMissingCredentialError("Linear")

    result = _run("linear_token", gateway, credential={})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No credential saved in the account"


def test_an_unreachable_linear_fails_only_a_form_run() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearUnreachableError("refused", timed_out=False)

    form = _run("linear_token", gateway, form_run=True)
    stored = _run("linear_token", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == "Cannot reach Linear"


def test_a_sign_in_timeout_says_so() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearUnreachableError("slow", timed_out=True)

    result = _run("linear_token", gateway, form_run=True)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Sign-in timed out"
    assert result.error_kind == CheckErrorKind.TIMEOUT


def test_a_busy_refresh_lock_is_incomplete() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearTokenLockError("busy")

    result = _run("linear_token", gateway, credential=_OAUTH_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Token refresh is busy elsewhere"


def test_a_query_linear_rejects_is_incomplete() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearGraphQLError([{"message": "bad field"}])

    result = _run("linear_token", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Linear rejected the query"


def test_an_api_error_carries_the_request_and_body() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearApiError(
        "500", status_code=500, body='{"error": "Server Error"}'
    )

    result = _run("linear_token", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Unexpected response from Linear"
    assert result.error_detail is not None
    assert result.error_detail.status_code == 500
    assert result.error_detail.request == "POST api.linear.app/graphql"
    assert result.error_detail.response_excerpt == '{"error": "Server Error"}'


def test_a_rate_limit_is_incomplete_and_stops_the_run() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearRateLimitError(
        "limited", status_code=400, body="RATELIMITED"
    )

    # A check that does not depend on sign-in, so only the stop holds it.
    results = _run_all(["linear_token", "linear_workspace_users"], gateway)

    sign_in = results["linear_token"]
    assert sign_in.status == CapabilityCheckStatus.INCOMPLETE
    assert sign_in.error_kind == CheckErrorKind.RATE_LIMITED
    assert sign_in.summary == "Rate limited by Linear"
    assert (
        results["linear_workspace_users"].not_run_reason
        == CheckNotRunReason.RATE_LIMITED
    )
    gateway.list_workspace_users.assert_not_called()


def test_a_failed_sign_in_stops_the_checks_after_it() -> None:
    gateway = _gateway()
    gateway.get_viewer.side_effect = LinearAuthError(
        "refused", status_code=401, body="refused"
    )

    results = _run_all(
        ["linear_token", "linear_teams", "linear_issues"],
        gateway,
        {"team_keys": ["ENG"]},
    )

    for check_id in ("linear_teams", "linear_issues"):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "linear_token"
    gateway.list_team_keys.assert_not_called()


# --- Find selected teams and projects ---


def test_finding_every_team_says_how_many() -> None:
    gateway = _gateway()
    gateway.list_team_keys.return_value = {"ENG", "DES"}

    one = _run("linear_teams", _gateway(), {"team_keys": ["ENG"]})
    two = _run("linear_teams", gateway, {"team_keys": ["ENG", "DES"]})

    assert one.summary == "Found team ENG"
    assert two.summary == "Found all 2 teams"


def test_some_teams_missing_is_partial_and_the_issues_check_runs() -> None:
    results = _run_all(
        ["linear_token", "linear_teams", "linear_issues"],
        _gateway(),
        {"team_keys": ["ENG", "DES"]},
    )

    teams = results["linear_teams"]
    assert teams.status == CapabilityCheckStatus.INCOMPLETE
    assert teams.partial
    assert teams.summary == "Team not found: DES"
    assert teams.description is not None and "Not found: DES." in teams.description
    assert results["linear_issues"].status == CapabilityCheckStatus.PASSED


def test_a_long_list_of_missing_teams_is_counted() -> None:
    keys: list[str] = ["ENG", *(f"MISSINGTEAM{n}" for n in range(4))]

    result = _run("linear_teams", _gateway(), {"team_keys": keys})

    assert result.summary == "4 of 5 teams not found"


def test_no_team_found_fails_and_stops_the_issues_check() -> None:
    gateway = _gateway()
    gateway.list_team_keys.return_value = set()

    results = _run_all(
        ["linear_teams", "linear_issues"], gateway, {"team_keys": ["DES"]}
    )

    teams = results["linear_teams"]
    assert teams.status == CapabilityCheckStatus.FAILED
    assert teams.summary == "No selected team found"
    assert results["linear_issues"].blocked_by == "linear_teams"


def test_some_projects_missing_is_partial() -> None:
    result = _run("linear_projects", _gateway(), {"projects": ["Roadmap", "Gone"]})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Project not found: Gone"


def test_a_paging_fault_says_so() -> None:
    gateway = _gateway()
    gateway.list_team_keys.side_effect = LinearPagingError("same cursor")

    result = _run("linear_teams", gateway, {"team_keys": ["ENG"]})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Linear paging stopped advancing"


# --- Sample issues ---


def test_sampling_names_the_issue_read() -> None:
    assert _run("linear_issues", _gateway()).summary == "Read issue ENG-1"


def test_an_empty_scope_fails() -> None:
    gateway = _gateway()
    gateway.iterate_issues.side_effect = lambda **_: iter([[]])

    scoped = _run("linear_issues", gateway, {"team_keys": ["ENG"]})
    unscoped = _run("linear_issues", gateway)

    assert scoped.status == unscoped.status == CapabilityCheckStatus.FAILED
    assert scoped.summary == "No issues in the selected scope"
    assert scoped.description == "No issue matches the selected teams and projects."
    assert unscoped.description == "The connected user sees no issue in Linear."


# --- Permission sync ---


def test_the_role_checks_share_one_row() -> None:
    results = _run_all(
        [
            "linear_workspace_member_doc_permission_sync",
            "linear_workspace_member_external_group_sync",
        ],
        _gateway(),
    )

    assert {result.row_id for result in results.values()} == {"linear_workspace_member"}
    for result in results.values():
        assert result.display_name == "Read account role"
        assert result.summary == "Connected user is a workspace member"


def test_a_guest_names_what_the_credential_needs() -> None:
    gateway = _gateway()
    gateway.get_viewer.return_value = LinearViewer(email="g@x.com", guest=True)

    result = _run("linear_workspace_member_external_group_sync", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.PERMISSION
    assert result.summary == "Connected user is a guest"
    assert result.description is not None and result.description.endswith(
        "Create the key as a workspace member, not a guest."
    )


def test_issue_sharing_names_the_team_of_the_issue_read() -> None:
    gateway = _gateway()

    result = _run("linear_issue_access", gateway)

    assert result.summary == "Read access of one ENG issue"
    gateway.get_issue_share.assert_called_once_with(issue_id="i1")


def test_issue_sharing_with_no_issue_is_incomplete() -> None:
    gateway = _gateway()
    gateway.iterate_issue_access.side_effect = lambda **_: iter([])

    result = _run("linear_issue_access", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No issue to read sharing of"


def test_a_failed_issue_sample_stops_issue_sharing() -> None:
    gateway = _gateway()
    gateway.iterate_issues.side_effect = lambda **_: iter([[]])

    results = _run_all(["linear_issues", "linear_issue_access"], gateway)

    assert results["linear_issue_access"].blocked_by == "linear_issues"


def test_listing_every_user_says_how_many() -> None:
    assert (
        _run("linear_workspace_users", _gateway()).summary
        == "Listed all 2 workspace users"
    )


def test_a_short_user_listing_fails_with_the_counts() -> None:
    gateway = _gateway()
    gateway.list_workspace_users.return_value = WorkspaceUsers(
        organization_id="o", user_count=5, users=[]
    )

    result = _run("linear_workspace_users", gateway, credential=_OAUTH_CREDENTIAL)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Listed 0 of 5 users"
    assert result.description is not None and result.description.endswith(
        "Reconnect through Linear as a workspace member, not a guest."
    )


def test_a_guest_stops_the_group_checks() -> None:
    gateway = _gateway()
    gateway.get_viewer.return_value = LinearViewer(email="g@x.com", guest=True)

    results = _run_all(
        [
            "linear_workspace_member_external_group_sync",
            "linear_workspace_users",
            "linear_team_members",
        ],
        gateway,
    )

    for check_id in ("linear_workspace_users", "linear_team_members"):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert (
            results[check_id].blocked_by
            == "linear_workspace_member_external_group_sync"
        )


def test_team_members_names_the_team_read() -> None:
    assert (
        _run("linear_team_members", _gateway()).summary == "Read 1 member of team ENG"
    )


def test_no_team_to_test_is_skipped() -> None:
    gateway = _gateway()
    gateway.list_teams.return_value = []

    result = _run("linear_team_members", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
    assert result.summary == "No teams to test"
