from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.capability_checks import build_github_indexing_checks
from onyx.connectors.github.config import REPOSITORY_OWNER_ERROR, GithubConnectorConfig
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import GitHubBranch
from onyx.connectors.github.source_operations import GitHubRateLimitError
from tests.unit.onyx.connectors.github.github_check_helpers import (
    CLASSIC_PUBLIC_ONLY_TOKEN,
    FINE_GRAINED_TOKEN,
    api_error,
    form_config,
    healthy_gateway,
    make_issue,
    make_repo,
)


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
) -> CapabilityCheckResult:
    checks: list[CapabilityCheck] = [
        check for check in build_github_indexing_checks() if check.check_id == check_id
    ]
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json={"github_access_token": "ghp_x"},
        connector_specific_config=config if config is not None else form_config(),
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


_RATE_LIMITED = GitHubRateLimitError("403", status_code=403, secondary=True)


def test_github_registers_named_indexing_checks() -> None:
    checks = get_capability_checks(DocumentSource.GITHUB)

    assert not any(check.is_fallback for check in checks)
    assert {check.check_id for check in checks} >= {
        "github_auth",
        "github_owner",
        "github_pull_requests",
    }


def test_every_check_passes_on_a_readable_organization() -> None:
    gateway = healthy_gateway()

    for repositories in ("", "docs"):
        for check in build_github_indexing_checks():
            result = _run(
                check.check_id,
                gateway,
                form_config(branch="main", repositories=repositories),
            )
            assert result.status == CapabilityCheckStatus.PASSED or (
                not result.applicable
            ), (check.check_id, result.message)


# --- github_auth / github_token_scopes ---


def test_auth_fails_for_a_rejected_token() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(401, "Bad credentials")

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "CredentialExpiredError"
    assert "wrong, expired, or revoked" in result.message


def test_auth_fails_for_a_url_without_a_github_api() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = api_error(404, "Not Found")

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Enterprise Server" in result.message


def test_auth_fails_for_an_unsafe_enterprise_server_url() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = ConnectorValidationError(
        "Invalid GitHub Enterprise Server URL"
    )

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED


def test_auth_is_incomplete_when_rate_limited() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.side_effect = _RATE_LIMITED

    result = _run("github_auth", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert "secondary rate limit" in result.message


def test_auth_runs_without_a_config() -> None:
    """A credential-time run has no config; the sign-in still runs."""
    gateway = healthy_gateway()
    (check,) = [
        c for c in build_github_indexing_checks() if c.check_id == "github_auth"
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json={},
        source_operations=gateway,
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.PASSED


def test_scopes_warn_for_a_classic_token_without_repo() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = CLASSIC_PUBLIC_ONLY_TOKEN

    result = _run("github_token_scopes", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert not result.required
    assert "`repo` scope" in result.message
    assert "read:org" in result.message


def test_scopes_skip_a_fine_grained_token() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = FINE_GRAINED_TOKEN

    result = _run("github_token_scopes", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.summary == "Token has no scopes to read"


# --- github_document_types ---


def test_document_types_fail_when_nothing_is_selected() -> None:
    result = _run(
        "github_document_types",
        healthy_gateway(),
        form_config(include_prs=False, include_issues=False, include_files=False),
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "indexes nothing" in result.message


# --- github_owner ---


def test_owner_passes_for_a_user() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = api_error(404, "Not Found")

    assert _run("github_owner", gateway).status == CapabilityCheckStatus.PASSED
    gateway.list_user_repositories.assert_called_once_with(login="acme", limit=1)


def test_owner_fails_when_no_organization_or_user_has_the_name() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = api_error(404, "Not Found")
    gateway.list_user_repositories.side_effect = api_error(404, "Not Found")

    result = _run("github_owner", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "no organization or user named `acme`" in result.message


def test_owner_names_missing_saml_authorization() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = api_error(
        403, "Resource protected by organization SAML enforcement.", sso_required=True
    )

    result = _run("github_owner", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "SAML single sign-on" in result.message
    assert "authorizing-a-personal-access-token" in result.message


def test_owner_is_incomplete_when_rate_limited() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = _RATE_LIMITED

    assert _run("github_owner", gateway).status == CapabilityCheckStatus.INCOMPLETE


# --- github_repositories_visible ---


def test_repositories_visible_fails_for_an_organization_without_visible_repos() -> None:
    gateway = healthy_gateway()
    gateway.list_organization_repositories.return_value = []

    result = _run("github_repositories_visible", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "No repository of the organization `acme`" in result.message
    assert "resource owner" in result.message


def test_repositories_visible_explains_a_user_lists_public_repos_only() -> None:
    gateway = healthy_gateway()
    gateway.get_organization.side_effect = api_error(404, "Not Found")

    result = _run("github_repositories_visible", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "only the public repositories" in result.message


def test_repositories_visible_does_not_apply_to_a_repository_list() -> None:
    result = _run(
        "github_repositories_visible", healthy_gateway(), form_config(repositories="a")
    )

    assert not result.applicable


# --- github_configured_repositories ---


def test_configured_repositories_pass_when_each_is_readable() -> None:
    gateway = healthy_gateway()

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a, b")
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert gateway.get_repository.call_count == 2


def test_configured_repositories_name_the_missing_scope() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = CLASSIC_PUBLIC_ONLY_TOKEN
    gateway.get_repository.side_effect = [make_repo("a"), api_error(404, "Not Found")]

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a,secret")
    )

    # One of two found: the checks after it run on the found one.
    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "1 of 2 repositories not found"
    assert result.description is not None
    assert "Not found: secret. Select the repo scope." in result.description


def test_configured_repositories_name_fine_grained_repository_access() -> None:
    gateway = healthy_gateway()
    gateway.get_token_info.return_value = FINE_GRAINED_TOKEN
    gateway.get_repository.side_effect = api_error(404, "Not Found")

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="secret")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "repository access does not include it" in result.message


def test_configured_repositories_with_an_owner_fail_as_a_setting() -> None:
    gateway = healthy_gateway()

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="acme/docs")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.INVALID
    assert f"repositories: {REPOSITORY_OWNER_ERROR}" in result.message
    gateway.get_repository.assert_not_called()


def test_configured_repositories_tell_apart_a_denial() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = api_error(
        403, "Resource protected by organization SAML enforcement."
    )

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "SAML single sign-on" in result.message


def test_configured_repositories_are_incomplete_when_rate_limited() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = _RATE_LIMITED

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a")
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE


# --- github_branch ---


def test_branch_fails_for_a_repository_without_it() -> None:
    gateway = healthy_gateway()
    gateway.get_branch.side_effect = api_error(404, "Branch not found")

    result = _run("github_branch", gateway, form_config(branch="gh-pages"))

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`gh-pages` does not exist in `acme/docs`" in result.message
    gateway.get_branch.assert_called_once_with(
        repo_full_name="acme/docs", branch="gh-pages"
    )


@pytest.mark.parametrize(
    "overrides",
    [{"branch": ""}, {"branch": "gh-pages", "include_files": False}],
    ids=["no-branch", "files-off"],
)
def test_branch_applies_only_to_files_on_a_branch(overrides: dict[str, Any]) -> None:
    assert not _run(
        "github_branch", healthy_gateway(), form_config(**overrides)
    ).applicable


# --- github_pull_requests / github_issues / github_files ---


def test_pull_requests_read_the_first_pull_request() -> None:
    gateway = healthy_gateway()

    assert _run("github_pull_requests", gateway).status == CapabilityCheckStatus.PASSED
    gateway.list_pull_requests.assert_called_once_with(
        repo_full_name="acme/docs", state="all", page=0
    )
    gateway.get_pull_request.assert_called_once_with(
        repo_full_name="acme/docs", number=1
    )


def test_pull_requests_name_the_missing_fine_grained_permission() -> None:
    gateway = healthy_gateway()
    gateway.list_pull_requests.side_effect = api_error(
        403,
        "Resource not accessible by personal access token",
        accepted_permissions="pull_requests=read",
    )

    result = _run("github_pull_requests", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "`pull_requests=read`" in result.message


def test_pull_requests_pass_when_the_repository_has_them_turned_off() -> None:
    gateway = healthy_gateway()
    gateway.list_pull_requests.side_effect = api_error(404, "Not Found")

    assert _run("github_pull_requests", gateway).status == CapabilityCheckStatus.PASSED


def test_pull_requests_skip_without_a_readable_repository() -> None:
    gateway = healthy_gateway()
    gateway.list_organization_repositories.return_value = []

    result = _run("github_pull_requests", gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.summary == "No repositories to test"


def test_issues_read_the_first_issue_that_is_not_a_pull_request() -> None:
    gateway = healthy_gateway()
    gateway.list_issues.return_value = [
        make_issue(5, is_pull_request=True),
        make_issue(6),
    ]

    assert _run("github_issues", gateway).status == CapabilityCheckStatus.PASSED
    gateway.get_issue.assert_called_once_with(repo_full_name="acme/docs", number=6)


def test_issues_name_the_missing_fine_grained_permission() -> None:
    gateway = healthy_gateway()
    gateway.list_issues.side_effect = api_error(
        403, "Resource not accessible", accepted_permissions="issues=read"
    )

    result = _run("github_issues", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`issues=read`" in result.message


def test_files_read_one_indexable_file() -> None:
    gateway = healthy_gateway()

    assert _run("github_files", gateway).status == CapabilityCheckStatus.PASSED
    gateway.get_git_tree.assert_called_once_with(repo_full_name="acme/docs", ref="main")
    gateway.get_file_content.assert_called_once_with(
        repo_full_name="acme/docs", path="README.md", ref="main"
    )


def test_files_are_incomplete_for_an_empty_repository() -> None:
    gateway = healthy_gateway()
    gateway.get_git_tree.side_effect = api_error(409, "Git Repository is empty.")

    result = _run("github_files", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No files found in acme/docs"


def test_files_name_the_missing_fine_grained_permission() -> None:
    gateway = healthy_gateway()
    gateway.get_file_content.side_effect = api_error(
        403, "Resource not accessible", accepted_permissions="contents=read"
    )

    result = _run("github_files", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`contents=read`" in result.message


def test_files_leave_a_missing_branch_to_the_branch_check() -> None:
    gateway = healthy_gateway()
    gateway.get_git_tree.side_effect = api_error(404, "Not Found")

    result = _run("github_files", gateway, form_config(branch="gh-pages"))

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert "github_branch" in result.message


def test_files_probe_the_listed_repositories() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = [
        api_error(404, "Not Found"),
        make_repo("b"),
    ]

    result = _run("github_files", gateway, form_config(repositories="missing, b"))

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_git_tree.assert_called_once_with(repo_full_name="acme/b", ref="main")


def test_files_skip_a_listed_repository_whose_files_are_denied() -> None:
    gateway = healthy_gateway()

    def list_root_contents(*, repo_full_name: str) -> list[str]:
        if repo_full_name == "acme/denied":
            raise api_error(403, "Resource not accessible")
        return []

    gateway.list_root_contents.side_effect = list_root_contents

    result = _run("github_files", gateway, form_config(repositories="denied, b"))

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_git_tree.assert_called_once_with(repo_full_name="acme/b", ref="main")


def test_configured_repositories_name_every_kind_of_failure() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = [
        make_repo("a"),
        api_error(404, "Not Found"),
        api_error(403, "Forbidden"),
        make_repo("empty"),
    ]

    def list_root_contents(*, repo_full_name: str) -> list[str]:
        if repo_full_name == "acme/empty":
            raise api_error(404, "This repository is empty.")
        return []

    gateway.list_root_contents.side_effect = list_root_contents

    result = _run(
        "github_configured_repositories",
        gateway,
        form_config(repositories="a, missing, denied, empty"),
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Cannot read 3 of 4 repositories"
    assert result.description is not None
    lines = result.description.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("Not found: missing.")
    assert lines[1].startswith("Denied: denied.")
    assert lines[2].startswith("Unreadable files: acme/empty.")


def test_configured_repositories_are_incomplete_during_a_github_outage() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = api_error(502, "Bad Gateway")

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a")
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE


def test_configured_repositories_need_readable_contents() -> None:
    """Index attempts read the root directory of each listed repository."""
    gateway = healthy_gateway()
    gateway.list_root_contents.side_effect = api_error(
        403, "Resource not accessible", accepted_permissions="contents=read"
    )

    result = _run(
        "github_configured_repositories", gateway, form_config(repositories="a")
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "`acme/a`: its files cannot be read" in result.message
    assert "`contents=read`" in result.message
    gateway.get_token_info.assert_not_called()


def test_branch_checks_every_listed_repository() -> None:
    gateway = healthy_gateway()
    names = [f"r{i}" for i in range(7)]

    def get_branch(*, repo_full_name: str, branch: str) -> GitHubBranch:
        if repo_full_name == "acme/r6":
            raise api_error(404, "Branch not found")
        return GitHubBranch(name=branch)

    gateway.get_branch.side_effect = get_branch

    result = _run(
        "github_branch",
        gateway,
        form_config(branch="gh-pages", repositories=", ".join(names)),
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`acme/r6`" in result.message
    assert gateway.get_branch.call_count == 7


def test_checks_and_connector_read_the_same_owner_and_repositories() -> None:
    config = GithubConnectorConfig.model_validate(
        {"repo_owner": " acme ", "repositories": " , ,"}
    )
    connector = GithubConnector(repo_owner=" acme ", repositories=" , ,")

    assert (config.repo_owner, config.repositories) == ("acme", None)
    assert (connector.repo_owner, connector.repositories) == ("acme", None)


def test_branch_applies_to_a_single_listed_repository_without_files() -> None:
    """Index attempts validate the branch of a single listed repository."""
    gateway = healthy_gateway()
    gateway.get_branch.side_effect = api_error(404, "Branch not found")

    result = _run(
        "github_branch",
        gateway,
        form_config(branch="gh-pages", include_files=False, repositories="docs"),
    )

    assert result.status == CapabilityCheckStatus.FAILED


def test_branch_is_incomplete_when_a_repository_read_fails() -> None:
    gateway = healthy_gateway()
    gateway.get_repository.side_effect = api_error(502, "Bad Gateway")

    result = _run(
        "github_branch", gateway, form_config(branch="gh-pages", repositories="docs")
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    gateway.get_branch.assert_not_called()


@pytest.mark.parametrize("check_id", ["github_pull_requests", "github_issues"])
def test_listings_pass_when_github_needs_cursor_pages(check_id: str) -> None:
    gateway = healthy_gateway()
    error = api_error(
        422, "Pagination with the page parameter is not supported. Use cursor"
    )
    gateway.list_pull_requests.side_effect = error
    gateway.list_issues.side_effect = error

    assert _run(check_id, gateway).status == CapabilityCheckStatus.PASSED


@pytest.mark.parametrize("check_id", ["github_pull_requests", "github_issues"])
def test_listings_fail_for_another_rejected_request(check_id: str) -> None:
    gateway = healthy_gateway()
    error = api_error(422, "Validation Failed")
    gateway.list_pull_requests.side_effect = error
    gateway.list_issues.side_effect = error

    result = _run(check_id, gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "HTTP 422" in result.message
