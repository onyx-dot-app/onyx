"""Runs the Confluence indexing checks against the live Cloud test site, with the
classic and the scoped API token. Read only."""

import os
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.confluence.capability_checks import (
    build_confluence_indexing_checks,
)
from onyx.connectors.confluence.source_operations import ConfluenceSourceOperations
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.CONFLUENCE_ACCESS_TOKEN,
    TestSecret.CONFLUENCE_ACCESS_TOKEN_SCOPED,
)

_SPACE = os.getenv("CONFLUENCE_TEST_SPACE") or "DailyConne"


def _form(scoped_token: bool, **scope: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty tab fields."""
    return {
        "wiki_base": os.environ["CONFLUENCE_TEST_SPACE_URL"],
        "is_cloud": os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true",
        "scoped_token": scoped_token,
        "space": "",
        "page_id": "",
        "index_recursively": True,
        "cql_query": "",
        "include_attachments": True,
        **scope,
    }


@pytest.mark.parametrize("scoped_token", [False, True], ids=["classic", "scoped"])
@pytest.mark.parametrize(
    "scope,mode_check_id",
    [
        ({"space": _SPACE}, "confluence_configured_space"),
        (
            {"cql_query": f"type=page and space='{_SPACE}'"},
            "confluence_cql_query",
        ),
    ],
    ids=["space", "cql"],
)
def test_indexing_checks_pass_on_the_test_space(
    test_secrets: dict[TestSecret, str],
    scoped_token: bool,
    scope: dict[str, Any],
    mode_check_id: str,
) -> None:
    secret = (
        TestSecret.CONFLUENCE_ACCESS_TOKEN_SCOPED
        if scoped_token
        else TestSecret.CONFLUENCE_ACCESS_TOKEN
    )
    credential_json = {
        "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        "confluence_access_token": test_secrets[secret].strip(),
    }
    config = _form(scoped_token, **scope)
    context = CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE,
        credential_json=credential_json,
        connector_specific_config=config,
        source_operations=ConfluenceSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.CONFLUENCE, credential_json
            ),
            connector_specific_config=config,
        ),
    )

    results = run_capability_checks(build_confluence_indexing_checks(), context)

    by_id = {result.check_id: result for result in results}
    failures = {
        result.check_id: result.message
        for result in results
        if result.applicable and result.status != CapabilityCheckStatus.PASSED
    }
    assert not failures, failures
    assert by_id[mode_check_id].status == CapabilityCheckStatus.PASSED
    auth_check_id = (
        "confluence_scoped_token_auth" if scoped_token else "confluence_auth"
    )
    assert by_id[auth_check_id].status == CapabilityCheckStatus.PASSED
    verdicts = compute_capability_verdicts({CredentialCapability.INDEXING}, results)
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.PASSED


def _scoped_auth_result(token: str) -> CapabilityCheckStatus:
    credential_json = {
        "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        "confluence_access_token": token,
    }
    config = _form(True, space=_SPACE)
    context = CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE,
        credential_json=credential_json,
        connector_specific_config=config,
        source_operations=ConfluenceSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.CONFLUENCE, credential_json
            ),
            connector_specific_config=config,
        ),
    )
    # Only the sign-in check, so each call makes one request.
    scoped_auth = [
        check
        for check in build_confluence_indexing_checks()
        if check.check_id == "confluence_scoped_token_auth"
    ]
    (auth,) = run_capability_checks(scoped_auth, context)
    return auth.status


def test_scoped_sign_in_fails_for_a_bad_token() -> None:
    # The scoped probe signs in through the api.atlassian.com gateway, as the
    # client does, so a bad token fails the sign-in check itself.
    assert _scoped_auth_result("not-a-real-token") == CapabilityCheckStatus.FAILED


def test_scoped_mode_accepts_a_classic_token(
    test_secrets: dict[TestSecret, str],
) -> None:
    # The gateway accepts classic API tokens too, so this setup works.
    token = test_secrets[TestSecret.CONFLUENCE_ACCESS_TOKEN].strip()
    assert _scoped_auth_result(token) == CapabilityCheckStatus.PASSED
