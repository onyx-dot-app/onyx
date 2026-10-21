"""Runs the GitHub capability checks against github.com with the daily test
token, on the ``onyx-dot-app`` organization. Read only."""

from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckErrorKind,
    CheckNotRunReason,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.github.capability_checks import (
    build_github_doc_permission_sync_checks,
    build_github_group_sync_checks,
    build_github_indexing_checks,
)
from onyx.connectors.github.source_operations import GitHubSourceOperations
from onyx.db.enums import AccessType
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.ACCESS_TOKEN_GITHUB)

_OWNER = "onyx-dot-app"
_REPOSITORY = "documentation"


def _form(**overrides: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty text fields."""
    return {
        "repo_owner": _OWNER,
        "repositories": _REPOSITORY,
        "include_prs": True,
        "include_issues": True,
        "include_files": True,
        "branch": "",
        **overrides,
    }


def _credential(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {"github_access_token": test_secrets[TestSecret.ACCESS_TOKEN_GITHUB].strip()}


def _results(
    credential_json: dict[str, Any],
    config: dict[str, Any],
    perm_sync: bool = False,
) -> dict[str, CapabilityCheckResult]:
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json=credential_json,
        connector_specific_config=config,
        access_type=AccessType.SYNC if perm_sync else None,
        source_operations=GitHubSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.GITHUB.value, credential_json
            ),
            connector_specific_config=config,
        ),
    )
    checks: list[CapabilityCheck] = (
        build_github_doc_permission_sync_checks() + build_github_group_sync_checks()
        if perm_sync
        else build_github_indexing_checks()
    )
    results: list[CapabilityCheckResult] = run_capability_checks(checks, context)
    return {result.check_id: result for result in results}


# `onyx-dot-app/documentation` can have no issue or pull request to read, so
# these probes can end INCOMPLETE as inconclusive.
_INCONCLUSIVE_PROBE_CHECK_IDS: frozenset[str] = frozenset(
    {"github_issues", "github_pull_requests"}
)


def _inconclusive_probe(check_id: str, result: CapabilityCheckResult) -> bool:
    return (
        check_id in _INCONCLUSIVE_PROBE_CHECK_IDS
        and result.status == CapabilityCheckStatus.INCOMPLETE
        and result.error_kind == CheckErrorKind.INCONCLUSIVE
    )


def _skipped_for_nothing_in_scope(
    result: CapabilityCheckResult, by_id: dict[str, CapabilityCheckResult]
) -> bool:
    """True for a skip with nothing in scope, or a skip that such a skip caused."""
    if result.status != CapabilityCheckStatus.SKIPPED:
        return False
    if result.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE:
        return True
    return (
        result.not_run_reason == CheckNotRunReason.DEPENDENCY_SKIPPED
        and result.blocked_by is not None
        and _skipped_for_nothing_in_scope(by_id[result.blocked_by], by_id)
    )


@pytest.mark.parametrize(
    "overrides,mode_check_id",
    [
        ({}, "github_configured_repositories"),
        ({"repositories": ""}, "github_repositories_visible"),
    ],
    ids=["listed-repository", "all-repositories"],
)
def test_indexing_checks_pass_on_the_test_organization(
    test_secrets: dict[TestSecret, str],
    overrides: dict[str, Any],
    mode_check_id: str,
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        _credential(test_secrets), _form(**overrides)
    )

    not_passed: dict[str, CapabilityCheckResult] = {
        check_id: result
        for check_id, result in by_id.items()
        if result.applicable
        and result.required
        and result.status != CapabilityCheckStatus.PASSED
    }
    failures: dict[str, str] = {
        check_id: f"{result.status}: {result.message}"
        for check_id, result in not_passed.items()
        # SKIPPED: the organization has nothing for the check to test.
        if result.status != CapabilityCheckStatus.SKIPPED
        and not _inconclusive_probe(check_id, result)
    }
    assert not failures, failures
    assert by_id[mode_check_id].status == CapabilityCheckStatus.PASSED
    verdicts: dict[CredentialCapability, CapabilityVerdict] = (
        compute_capability_verdicts(
            {CredentialCapability.INDEXING}, list(by_id.values())
        )
    )
    # A required inconclusive probe leaves the verdict INDETERMINATE.
    expected: set[CapabilityVerdict] = (
        {CapabilityVerdict.INDETERMINATE}
        if any(
            result.status == CapabilityCheckStatus.INCOMPLETE
            for result in not_passed.values()
        )
        else {CapabilityVerdict.PASSED, CapabilityVerdict.PASSED_WITH_WARNINGS}
    )
    assert verdicts[CredentialCapability.INDEXING] in expected, verdicts


@pytest.mark.parametrize(
    "credential_override,overrides,check_id,message",
    [
        (
            {"github_access_token": "ghp_not-a-real-token"},
            {},
            "github_auth",
            "HTTP 401",
        ),
        (
            {},
            {"repo_owner": "onyx-dot-app-no-such-owner-7f3a", "repositories": ""},
            "github_owner",
            "no organization or user named",
        ),
        (
            {},
            {"repositories": "no-such-repository-7f3a"},
            "github_configured_repositories",
            "`onyx-dot-app/no-such-repository-7f3a`: not found",
        ),
        (
            {},
            {"branch": "no-such-branch-7f3a"},
            "github_branch",
            "`no-such-branch-7f3a` does not exist",
        ),
        (
            {},
            {"include_prs": False, "include_issues": False, "include_files": False},
            "github_document_types",
            "indexes nothing",
        ),
    ],
    ids=[
        "bad-token",
        "unknown-owner",
        "unknown-repository",
        "unknown-branch",
        "nothing-selected",
    ],
)
def test_invalid_configs_fail(
    test_secrets: dict[TestSecret, str],
    credential_override: dict[str, Any],
    overrides: dict[str, Any],
    check_id: str,
    message: str,
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        {**_credential(test_secrets), **credential_override}, _form(**overrides)
    )

    result: CapabilityCheckResult = by_id[check_id]
    assert result.status == CapabilityCheckStatus.FAILED, result
    assert message in result.message, result.message


@pytest.mark.parametrize(
    "overrides",
    [{}, {"repositories": ""}],
    ids=["listed-repository", "all-repositories"],
)
def test_perm_sync_checks_pass_on_the_test_organization(
    test_secrets: dict[TestSecret, str],
    overrides: dict[str, Any],
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        _credential(test_secrets), _form(**overrides), perm_sync=True
    )

    not_passed: dict[str, CapabilityCheckResult] = {
        check_id: result
        for check_id, result in by_id.items()
        if result.applicable
        and result.required
        and result.status != CapabilityCheckStatus.PASSED
    }
    # A public repository has no collaborator or member to read.
    failures: dict[str, str] = {
        check_id: f"{result.status}: {result.message}"
        for check_id, result in not_passed.items()
        if not _skipped_for_nothing_in_scope(result, by_id)
    }
    assert not failures, failures
    verdicts: dict[CredentialCapability, CapabilityVerdict] = (
        compute_capability_verdicts(
            {
                CredentialCapability.DOC_PERMISSION_SYNC,
                CredentialCapability.EXTERNAL_GROUP_SYNC,
            },
            list(by_id.values()),
        )
    )
    for capability, passing in (
        (CredentialCapability.DOC_PERMISSION_SYNC, {CapabilityVerdict.PASSED}),
        (
            CredentialCapability.EXTERNAL_GROUP_SYNC,
            {CapabilityVerdict.PASSED, CapabilityVerdict.PASSED_WITH_WARNINGS},
        ),
    ):
        expected: set[CapabilityVerdict] = (
            {CapabilityVerdict.SKIPPED}
            if any(result.capability == capability for result in not_passed.values())
            else passing
        )
        assert verdicts[capability] in expected, (capability, verdicts[capability])
