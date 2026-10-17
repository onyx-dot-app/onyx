from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.github.capability_checks import (
    build_github_doc_permission_sync_checks,
    build_github_group_sync_checks,
)
from onyx.connectors.github.models import (
    GitHubRepository,
    GitHubTokenInfo,
    GitHubTokenKind,
    GitHubUser,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
    GitHubSourceOperations,
)
from onyx.db.enums import AccessType
from tests.unit.onyx.connectors.github.conftest import raw_repository

_CLASSIC = GitHubTokenInfo(
    login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["repo", "read:org"]
)
_CLASSIC_WITHOUT_ORG = GitHubTokenInfo(
    login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["repo"]
)


def _repo(name: str, visibility: str, **overrides: Any) -> GitHubRepository:
    return GitHubRepository.from_raw(
        raw_repository(name=name, owner="acme", visibility=visibility, **overrides)
    )


def _gateway(repositories: list[GitHubRepository] | None = None) -> MagicMock:
    """An organization ``acme`` with a private and an internal repository,
    whose groups have one member with a public email."""
    gateway: MagicMock = create_autospec(GitHubSourceOperations, instance=True)
    gateway.get_token_info.return_value = _CLASSIC
    gateway.list_organization_repositories.return_value = (
        repositories
        if repositories is not None
        else [_repo("docs", "private"), _repo("handbook", "internal")]
    )
    gateway.list_repository_collaborators.return_value = ["octocat"]
    gateway.list_organization_members.return_value = ["octocat"]
    gateway.get_user.side_effect = lambda *, login: GitHubUser(
        login=login, email=f"{login}@example.com"
    )
    return gateway


def _run(
    check_id: str,
    gateway: MagicMock,
    access_type: AccessType = AccessType.SYNC,
) -> CapabilityCheckResult:
    checks: list[CapabilityCheck] = [
        check
        for check in build_github_doc_permission_sync_checks()
        + build_github_group_sync_checks()
        if check.check_id == check_id
    ]
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json={"github_access_token": "ghp_x"},
        connector_specific_config={"repo_owner": "acme", "repositories": ""},
        access_type=access_type,
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


def _api_error(status: int, **kwargs: Any) -> GitHubApiError:
    return GitHubApiError(f"{status}", status_code=status, **kwargs)


@pytest.mark.usefixtures("enable_ee")
def test_github_registers_named_perm_sync_checks() -> None:
    checks = get_perm_sync_capability_checks(DocumentSource.GITHUB)

    assert {(check.capability, check.check_id) for check in checks} == {
        (
            CredentialCapability.DOC_PERMISSION_SYNC,
            "github_repository_visibility",
        ),
        (
            CredentialCapability.EXTERNAL_GROUP_SYNC,
            "github_repository_collaborators",
        ),
        (
            CredentialCapability.EXTERNAL_GROUP_SYNC,
            "github_organization_members",
        ),
        (CredentialCapability.EXTERNAL_GROUP_SYNC, "github_user_emails"),
    }


def test_every_check_passes_on_a_readable_organization() -> None:
    gateway = _gateway()

    for check in (
        build_github_doc_permission_sync_checks() + build_github_group_sync_checks()
    ):
        result = _run(check.check_id, gateway)
        assert result.status == CapabilityCheckStatus.PASSED, (
            check.check_id,
            result.message,
        )


def test_checks_do_not_apply_without_permission_sync() -> None:
    assert not _run(
        "github_repository_visibility", _gateway(), AccessType.PUBLIC
    ).applicable


# --- github_repository_visibility ---


def test_visibility_fails_for_an_internal_repository_without_an_organization() -> None:
    user_owned = raw_repository(name="x", owner="octocat", visibility="internal")
    user_owned["owner"] = {"login": "octocat", "id": 7, "type": "User"}
    gateway = _gateway([GitHubRepository.from_raw(user_owned)])

    result = _run("github_repository_visibility", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`octocat/x`" in result.message


def test_visibility_is_indeterminate_without_a_readable_repository() -> None:
    result = _run("github_repository_visibility", _gateway([]))

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    assert "github_repositories_visible" in result.message


def test_visibility_is_indeterminate_when_rate_limited() -> None:
    gateway = _gateway()
    gateway.list_organization_repositories.side_effect = GitHubRateLimitError(
        "403", status_code=403, secondary=False
    )

    result = _run("github_repository_visibility", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE


# --- github_repository_collaborators ---


def test_collaborators_are_read_for_the_first_private_repository() -> None:
    gateway = _gateway()

    assert (
        _run("github_repository_collaborators", gateway).status
        == CapabilityCheckStatus.PASSED
    )
    # A probe reads at most six logins, not the whole group.
    gateway.list_repository_collaborators.assert_called_once_with(
        repo_full_name="acme/docs", limit=6
    )


def test_collaborators_are_not_read_without_a_private_repository() -> None:
    gateway = _gateway([_repo("site", "public"), _repo("handbook", "internal")])

    assert (
        _run("github_repository_collaborators", gateway).status
        == CapabilityCheckStatus.PASSED
    )
    gateway.list_repository_collaborators.assert_not_called()


def test_collaborators_name_push_access_and_the_missing_scope() -> None:
    gateway = _gateway()
    gateway.get_token_info.return_value = _CLASSIC_WITHOUT_ORG
    gateway.list_repository_collaborators.side_effect = _api_error(
        403, github_message="Must have push access to view repository collaborators."
    )

    result = _run("github_repository_collaborators", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "`read:org`" in result.message
    assert "write (push) access" in result.message


# --- github_organization_members ---


def test_members_are_read_for_an_internal_repository() -> None:
    gateway = _gateway()

    assert (
        _run("github_organization_members", gateway).status
        == CapabilityCheckStatus.PASSED
    )
    gateway.list_organization_members.assert_called_once_with(org_login="acme", limit=6)


def test_members_are_not_read_without_an_internal_repository() -> None:
    gateway = _gateway([_repo("docs", "private")])

    assert (
        _run("github_organization_members", gateway).status
        == CapabilityCheckStatus.PASSED
    )
    gateway.list_organization_members.assert_not_called()


def test_members_fail_for_a_classic_token_without_read_org() -> None:
    """GitHub lists only public members then, with no error."""
    gateway = _gateway()
    gateway.get_token_info.return_value = _CLASSIC_WITHOUT_ORG

    result = _run("github_organization_members", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "no `read:org` scope" in result.message
    assert "only the public members of `acme`" in result.message


def test_members_name_the_fine_grained_permission_on_a_denial() -> None:
    gateway = _gateway()
    gateway.get_token_info.return_value = GitHubTokenInfo(
        login="octocat", kind=GitHubTokenKind.FINE_GRAINED
    )
    gateway.list_organization_members.side_effect = _api_error(
        403, accepted_permissions="members=read"
    )

    result = _run("github_organization_members", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "`members=read`" in result.message


# --- github_user_emails ---


def test_emails_warn_when_no_user_has_a_public_email() -> None:
    gateway = _gateway()
    gateway.get_user.side_effect = lambda *, login: GitHubUser(login=login)

    result = _run("github_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert not result.required
    assert "public email" in result.message


def test_emails_are_indeterminate_for_a_partial_sample() -> None:
    gateway = _gateway()
    gateway.list_repository_collaborators.return_value = [f"u{i}" for i in range(9)]
    gateway.get_user.side_effect = lambda *, login: GitHubUser(login=login)

    result = _run("github_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    assert gateway.get_user.call_count == 5


def test_emails_read_organization_members_without_a_private_repository() -> None:
    gateway = _gateway([_repo("handbook", "internal")])

    assert _run("github_user_emails", gateway).status == CapabilityCheckStatus.PASSED
    gateway.get_user.assert_called_once_with(login="octocat")


def test_emails_are_indeterminate_when_the_group_cannot_be_read() -> None:
    gateway = _gateway()
    gateway.list_repository_collaborators.side_effect = _api_error(403)

    result = _run("github_user_emails", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    assert "github_repository_collaborators" in result.message


@pytest.mark.parametrize("scope", ["write:org", "admin:org"])
def test_members_accept_scopes_that_include_read_org(scope: str) -> None:
    gateway = _gateway()
    gateway.get_token_info.return_value = GitHubTokenInfo(
        login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["repo", scope]
    )

    assert (
        _run("github_organization_members", gateway).status
        == CapabilityCheckStatus.PASSED
    )
    gateway.list_organization_members.assert_called_once()


def test_collaborators_are_indeterminate_when_the_sample_is_cut() -> None:
    """20 public repositories can hide a private one."""
    gateway = _gateway([_repo(f"site{i}", "public") for i in range(21)])

    result = _run("github_repository_collaborators", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    assert "first 20 repositories include no private" in result.message


@pytest.mark.parametrize(
    "check_id", ["github_organization_members", "github_user_emails"]
)
def test_a_cut_sample_probes_the_owner_organization(check_id: str) -> None:
    """20 public repositories can hide an internal one, whose group is the
    owner organization's members."""
    gateway = _gateway([_repo(f"site{i}", "public") for i in range(21)])

    assert _run(check_id, gateway).status == CapabilityCheckStatus.PASSED
    gateway.list_organization_members.assert_called_once_with(org_login="acme", limit=6)


def test_group_checks_pass_when_every_repository_is_public() -> None:
    gateway = _gateway([_repo("site", "public")])

    for check_id in (
        "github_repository_collaborators",
        "github_organization_members",
        "github_user_emails",
    ):
        assert _run(check_id, gateway).status == CapabilityCheckStatus.PASSED


def test_twenty_public_repositories_are_a_complete_sample() -> None:
    """With nothing left unread, no member read is needed, and a token
    without read:org passes."""
    gateway = _gateway([_repo(f"site{i}", "public") for i in range(20)])
    gateway.get_token_info.return_value = _CLASSIC_WITHOUT_ORG

    for check_id in ("github_repository_collaborators", "github_organization_members"):
        assert _run(check_id, gateway).status == CapabilityCheckStatus.PASSED
    gateway.list_organization_members.assert_not_called()


def test_an_unsampled_organization_without_read_org_is_indeterminate() -> None:
    """Members of the owner organization may be needed only when unread
    repositories are internal, so a missing scope is not a failure."""
    gateway = _gateway([_repo(f"site{i}", "public") for i in range(21)])
    gateway.get_token_info.return_value = _CLASSIC_WITHOUT_ORG

    result = _run("github_organization_members", gateway)

    assert result.status == CapabilityCheckStatus.INDETERMINATE
    assert "no `read:org` scope" in result.message
