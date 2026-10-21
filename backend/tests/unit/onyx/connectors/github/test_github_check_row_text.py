"""The GitHub checks' rows: the design's short lines and descriptions, the
partial Find of selected repositories, the run order, and what a check that
tested nothing says."""

from typing import Any
from unittest.mock import MagicMock

import requests

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
from onyx.connectors.github.capability_checks import build_github_indexing_checks
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from tests.unit.onyx.connectors.github.github_check_helpers import (
    CLASSIC_PUBLIC_ONLY_TOKEN,
    FINE_GRAINED_TOKEN,
    api_error,
    form_config,
    healthy_gateway,
    make_repo,
)


def _run_all(
    check_ids: list[str],
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    *,
    form_run: bool = False,
) -> dict[str, CapabilityCheckResult]:
    checks: list[CapabilityCheck] = [
        check for check in build_github_indexing_checks() if check.check_id in check_ids
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json={"github_access_token": "ghp_x"},
        connector_specific_config=config if config is not None else form_config(),
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
    form_run: bool = False,
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, config, form_run=form_run)[check_id]


# --- Sign in to GitHub ---


def test_sign_in_names_the_token_user() -> None:
    result = _run("github_auth", healthy_gateway())

    assert result.display_name == "Sign in to GitHub"
    assert result.summary == "Signed in as @octocat"


def test_a_revoked_token_is_rejected() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(401, "Bad credentials")

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Token is invalid, expired or revoked"


def test_a_saml_denial_says_so() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(
        403, "Resource protected by organization SAML enforcement."
    )

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Token not authorized for SAML SSO"


def test_a_404_at_sign_in_is_no_api_at_the_url() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(404, "Not Found")

    assert _run("github_auth", gateway).summary == "No GitHub API at this URL"


def test_a_missing_token_says_so() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = ConnectorMissingCredentialError("GitHub")

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No token saved in the account"


def test_an_unreachable_server_fails_only_a_form_run() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = requests.ConnectionError("refused")

    form = _run("github_auth", gateway, form_run=True)
    stored = _run("github_auth", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == "Cannot reach GitHub"


def test_a_rate_limit_is_incomplete_and_stops_the_run() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = GitHubRateLimitError(
        "429", status_code=429, secondary=False
    )

    results = _run_all(["github_auth", "github_document_types"], gateway)

    auth = results["github_auth"]
    assert auth.status == CapabilityCheckStatus.INCOMPLETE
    assert auth.error_kind == CheckErrorKind.RATE_LIMITED
    assert auth.summary == "Rate limited by GitHub"
    assert (
        results["github_document_types"].not_run_reason
        == CheckNotRunReason.RATE_LIMITED
    )


def test_a_failed_sign_in_stops_the_checks_after_it() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(401, "Bad credentials")

    results = _run_all(
        ["github_auth", "github_owner", "github_repositories_visible", "github_issues"],
        gateway,
    )

    for check_id in ("github_owner", "github_repositories_visible", "github_issues"):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "github_auth"
    gateway.get_organization.assert_not_called()


def test_an_api_error_carries_the_request_and_body() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = GitHubApiError(
        "500",
        status_code=500,
        method="GET",
        url="https://api.github.com/user",
        body='{"message": "Server Error"}',
    )

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Unexpected response from GitHub"
    assert result.error_detail is not None
    assert result.error_detail.request == "GET api.github.com/user"
    assert result.error_detail.response_excerpt == '{"message": "Server Error"}'


# --- Selected content, token scopes, owner, repositories ---


def test_selected_content_names_what_is_indexed() -> None:
    result = _run(
        "github_document_types", healthy_gateway(), form_config(include_issues=False)
    )

    assert result.summary == "Indexing pull requests, documents"


def test_a_classic_token_without_repo_names_the_scope() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = CLASSIC_PUBLIC_ONLY_TOKEN

    result = _run("github_token_scopes", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Classic token lacks the repo scope"


def test_owner_names_its_kind() -> None:
    assert _run("github_owner", healthy_gateway()).summary == "Found organization acme"


def test_a_missing_owner_names_it() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = api_error(404, "Not Found")
    gateway.list_user_repositories.side_effect = api_error(404, "Not Found")

    assert _run("github_owner", gateway).summary == "No owner named acme"


def test_list_repositories_counts_them() -> None:
    gateway = healthy_gateway()
    gateway.list_organization_repositories.return_value = [
        make_repo("a"),
        make_repo("b"),
    ]

    assert (
        _run("github_repositories_visible", gateway).summary == "2 repositories visible"
    )


# --- Find selected repos ---


def test_all_selected_repositories_found() -> None:
    result = _run(
        "github_configured_repositories",
        healthy_gateway(),
        form_config(repositories="a, b"),
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "All 2 selected repositories readable"


def test_some_denied_repositories_are_incomplete() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = [make_repo("a"), api_error(403, "Forbidden")]

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a, b")
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.partial
    assert result.summary == "Token denied 1 of 2 repositories"


def test_no_selected_repository_found_fails() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = api_error(404, "Not Found")

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a, b")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No selected repo found"


def test_checks_after_a_partial_find_run_on_the_found_repositories() -> None:
    gateway = healthy_gateway()
    found = make_repo("a")
    missing = api_error(404, "Not Found")
    gateway.get_repository.side_effect = [found, missing, found, missing]

    results = _run_all(
        ["github_owner", "github_configured_repositories", "github_pull_requests"],
        gateway,
        form_config(repositories="a, gone"),
    )

    assert (
        results["github_configured_repositories"].status
        == CapabilityCheckStatus.INCOMPLETE
    )
    assert results["github_pull_requests"].status == CapabilityCheckStatus.PASSED
    assert results["github_pull_requests"].summary == "Read pull request #1"


# --- Samples ---


def test_branch_names_the_repositories_without_it() -> None:
    gateway = healthy_gateway()
    gateway.get_branch.side_effect = api_error(404, "Branch not found")

    result = _run("github_branch", gateway, form_config(branch="gh-pages"))

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Branch not found in 1 repository"


def test_pull_requests_turned_off_pass_with_a_caveat() -> None:
    gateway = healthy_gateway()
    gateway.list_pull_requests.side_effect = api_error(404, "Not Found")

    result = _run("github_pull_requests", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Pull requests are off in acme/docs"
    assert result.advisories


def test_no_pull_requests_to_read_is_incomplete() -> None:
    gateway = healthy_gateway()
    gateway.list_pull_requests.return_value = []

    result = _run("github_pull_requests", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No pull requests found to test"


def test_no_issues_to_read_is_incomplete() -> None:
    gateway = healthy_gateway()
    gateway.list_issues.return_value = []

    result = _run("github_issues", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No issues found to test"


def test_files_count_the_documents() -> None:
    result = _run("github_files", healthy_gateway())

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "1 document found in acme/docs"


def test_a_denied_sample_names_the_fine_grained_permission() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = FINE_GRAINED_TOKEN
    gateway.list_issues.side_effect = api_error(403, "Resource not accessible")

    result = _run("github_issues", gateway)

    assert result.summary == "Token cannot read issues"
    assert result.description is not None
    assert result.description.endswith("Give the token read access to Issues.")
