"""Runs the SharePoint permission-sync checks against the live test tenant:
the certificate app passes, and the client-secret app and a foreign site fail
their checks. Read only."""

import os
from typing import Any

import pytest

from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
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
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.SHAREPOINT_CLIENT_SECRET,
    TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
    TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
    TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
    TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
)
_CAPABILITIES = {CredentialCapability.DOC_PERMISSION_SYNC}


def _certificate_credentials(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "authentication_method": MicrosoftAuthMethod.CERTIFICATE.value,
        "sp_client_id": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        "sp_private_key": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        "sp_certificate_password": test_secrets[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
        "sp_directory_id": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
    }


def _secret_credentials(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
        "sp_client_secret": test_secrets[TestSecret.SHAREPOINT_CLIENT_SECRET],
        "sp_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
    }


def _site(suffix: str = "") -> str:
    return os.environ["SHAREPOINT_SITE"] + suffix


def _config(sites: list[str], **overrides: Any) -> dict[str, Any]:
    return {
        "sites": sites,
        "include_site_documents": True,
        "include_site_pages": True,
        **overrides,
    }


def _run(
    credentials: dict[str, Any], config: dict[str, Any]
) -> tuple[list[CapabilityCheckResult], dict[CredentialCapability, CapabilityVerdict]]:
    context = CapabilityCheckContext(
        source=DocumentSource.SHAREPOINT,
        credential_json=credentials,
        connector_specific_config=config,
        source_operations=SharepointSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.SHAREPOINT, credentials
            ),
            connector_specific_config=config,
        ),
    )
    results = run_capability_checks(
        get_perm_sync_capability_checks(DocumentSource.SHAREPOINT), context
    )
    return results, compute_capability_verdicts(_CAPABILITIES, results)


def _not_passed(results: list[CapabilityCheckResult]) -> dict[str, str | None]:
    return {
        result.check_id: result.message
        for result in results
        if result.status
        not in (CapabilityCheckStatus.PASSED, CapabilityCheckStatus.SKIPPED)
    }


def _perm_verdicts(
    verdicts: dict[CredentialCapability, CapabilityVerdict],
) -> set[CapabilityVerdict]:
    return {verdicts[capability] for capability in _CAPABILITIES}


def _failed(results: list[CapabilityCheckResult]) -> set[str]:
    return {
        result.check_id
        for result in results
        if result.status is CapabilityCheckStatus.FAILED
    }


@pytest.mark.parametrize(
    "site_suffixes",
    [[], [""], ["/Shared Documents/test"]],
    ids=["all-sites", "site", "folder"],
)
def test_the_certificate_app_passes(
    test_secrets: dict[TestSecret, str], site_suffixes: list[str]
) -> None:
    sites = [_site(suffix) for suffix in site_suffixes]

    results, verdicts = _run(
        _certificate_credentials(test_secrets),
        _config(sites, exhaustive_ad_enumeration=True),
    )

    assert _not_passed(results) == {}
    assert _perm_verdicts(verdicts) == {CapabilityVerdict.PASSED}


def test_a_client_secret_app_fails_the_certificate_check(
    test_secrets: dict[TestSecret, str],
) -> None:
    results, verdicts = _run(_secret_credentials(test_secrets), _config([_site()]))

    assert "sharepoint_certificate_auth" in _failed(results)
    assert _perm_verdicts(verdicts) == {CapabilityVerdict.FAILED}


def test_a_foreign_site_fails_the_site_permissions_check(
    test_secrets: dict[TestSecret, str],
) -> None:
    results, verdicts = _run(
        _certificate_credentials(test_secrets),
        _config(["https://victim.sharepoint.com/sites/x"]),
    )

    assert "sharepoint_site_permissions_read" in _failed(results)
    assert _perm_verdicts(verdicts) == {CapabilityVerdict.FAILED}
