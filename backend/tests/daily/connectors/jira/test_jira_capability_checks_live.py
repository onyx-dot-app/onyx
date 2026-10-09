"""Runs the Jira capability checks against the live Cloud test site, with the
classic and the scoped API token. Read only."""

from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.capability_checks import build_jira_indexing_checks
from onyx.connectors.jira.source_operations import JiraSourceOperations
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_API_TOKEN_SCOPED,
)

_SITE = "https://danswerai.atlassian.net"
_PROJECT = "AS"


def _form(scoped_token: bool, **scope: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty tab fields."""
    return {
        "jira_base_url": _SITE,
        "scoped_token": scoped_token,
        "project_key": "",
        "jql_query": "",
        **scope,
    }


def _credential(
    test_secrets: dict[TestSecret, str], scoped_token: bool
) -> dict[str, Any]:
    secret: TestSecret = (
        TestSecret.JIRA_API_TOKEN_SCOPED if scoped_token else TestSecret.JIRA_API_TOKEN
    )
    return {
        "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
        "jira_api_token": test_secrets[secret].strip(),
    }


def _results(
    credential_json: dict[str, Any], config: dict[str, Any]
) -> dict[str, CapabilityCheckResult]:
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json=credential_json,
        connector_specific_config=config,
        source_operations=JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA.value, credential_json
            ),
            connector_specific_config=config,
        ),
    )
    results: list[CapabilityCheckResult] = run_capability_checks(
        build_jira_indexing_checks(), context
    )
    return {result.check_id: result for result in results}


@pytest.mark.parametrize("scoped_token", [False, True], ids=["classic", "scoped"])
@pytest.mark.parametrize(
    "scope,mode_check_id",
    [
        ({"project_key": _PROJECT}, "jira_configured_project"),
        ({"jql_query": f'project = "{_PROJECT}"'}, "jira_jql_query"),
        ({}, None),
    ],
    ids=["project", "jql", "everything"],
)
def test_indexing_checks_pass_on_the_test_site(
    test_secrets: dict[TestSecret, str],
    scoped_token: bool,
    scope: dict[str, Any],
    mode_check_id: str | None,
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        _credential(test_secrets, scoped_token), _form(scoped_token, **scope)
    )

    failures: dict[str, str] = {
        check_id: result.message
        for check_id, result in by_id.items()
        if result.applicable and result.status != CapabilityCheckStatus.PASSED
    }
    assert not failures, failures
    if mode_check_id is not None:
        assert by_id[mode_check_id].status == CapabilityCheckStatus.PASSED
    auth_check_id = "jira_scoped_token_auth" if scoped_token else "jira_auth"
    assert by_id[auth_check_id].status == CapabilityCheckStatus.PASSED
    verdicts: dict[CredentialCapability, CapabilityVerdict] = (
        compute_capability_verdicts(
            {CredentialCapability.INDEXING}, list(by_id.values())
        )
    )
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.PASSED


@pytest.mark.parametrize(
    "credential_override,scope,check_id,message",
    [
        (
            {"jira_api_token": "not-a-real-token"},
            {"project_key": _PROJECT},
            "jira_auth",
            "HTTP 401",
        ),
        (
            {"jira_user_email": None},
            {"project_key": _PROJECT},
            "jira_auth",
            "has no email",
        ),
        ({}, {"project_key": "NOPE"}, "jira_configured_project", "`NOPE`"),
        (
            {},
            {"project_key": "DailyConnectorTestProject"},
            "jira_configured_project",
            "Did you mean the key `AS`?",
        ),
        ({}, {"jql_query": "project = AS"}, "jira_jql_query", "reserved JQL word"),
        (
            {},
            {"jql_query": 'project = "AS" ORDER BY created'},
            "jira_jql_query",
            "ORDER BY",
        ),
        ({}, {"jql_query": "project = ("}, "jira_jql_query", "HTTP 400"),
    ],
    ids=[
        "bad-token",
        "no-email-on-cloud",
        "unknown-project",
        "project-name-not-key",
        "reserved-word",
        "order-by",
        "bad-syntax",
    ],
)
def test_invalid_configs_fail(
    test_secrets: dict[TestSecret, str],
    credential_override: dict[str, Any],
    scope: dict[str, Any],
    check_id: str,
    message: str,
) -> None:
    credential_json: dict[str, Any] = {
        **_credential(test_secrets, False),
        **credential_override,
    }

    by_id: dict[str, CapabilityCheckResult] = _results(
        credential_json, _form(False, **scope)
    )

    result: CapabilityCheckResult = by_id[check_id]
    assert result.status == CapabilityCheckStatus.FAILED, result
    assert message in result.message, result.message


def test_scoped_sign_in_fails_for_a_bad_token(
    test_secrets: dict[TestSecret, str],
) -> None:
    credential_json: dict[str, Any] = {
        **_credential(test_secrets, True),
        "jira_api_token": "not-a-real-token",
    }

    by_id: dict[str, CapabilityCheckResult] = _results(
        credential_json, _form(True, project_key=_PROJECT)
    )

    result: CapabilityCheckResult = by_id["jira_scoped_token_auth"]
    assert result.status == CapabilityCheckStatus.FAILED, result
