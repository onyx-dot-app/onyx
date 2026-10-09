"""Runs the SharePoint indexing checks against the live test tenant, with the
settings an admin can get right and wrong. Read only."""

import os
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
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_indexing_checks,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.SHAREPOINT_CLIENT_SECRET)


def _credentials(
    test_secrets: dict[TestSecret, str], secret: str | None = None
) -> dict[str, Any]:
    return {
        "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
        "sp_client_secret": secret or test_secrets[TestSecret.SHAREPOINT_CLIENT_SECRET],
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
    credentials: dict[str, Any], config: dict[str, Any] | None
) -> tuple[list[CapabilityCheckResult], CapabilityVerdict]:
    context = CapabilityCheckContext(
        source=DocumentSource.SHAREPOINT,
        credential_json=credentials,
        connector_specific_config=config,
        source_operations=SharepointSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.SHAREPOINT, credentials
            ),
            connector_specific_config=config or {},
        ),
    )
    results = run_capability_checks(build_sharepoint_indexing_checks(), context)
    verdict = compute_capability_verdicts({CredentialCapability.INDEXING}, results)
    return results, verdict[CredentialCapability.INDEXING]


def _statuses(results: list[CapabilityCheckResult]) -> dict[str, CapabilityCheckStatus]:
    return {result.check_id: result.status for result in results}


@pytest.mark.parametrize(
    "site_suffixes",
    [[], [""], ["/Other Library"], ["/Shared Documents/test"]],
    ids=["all-sites", "site", "library", "folder"],
)
def test_the_test_tenant_passes(
    test_secrets: dict[TestSecret, str], site_suffixes: list[str]
) -> None:
    sites = [_site(suffix) for suffix in site_suffixes]

    results, verdict = _run(_credentials(test_secrets), _config(sites))

    not_passed = {
        result.check_id: result.message
        for result in results
        if result.status
        not in (CapabilityCheckStatus.PASSED, CapabilityCheckStatus.SKIPPED)
    }
    assert not_passed == {}
    assert verdict is CapabilityVerdict.PASSED


def test_a_bad_secret_fails_the_token_check(
    test_secrets: dict[TestSecret, str],
) -> None:
    results, verdict = _run(
        _credentials(test_secrets, secret="not-the-secret"), _config([_site()])
    )

    assert _statuses(results)["sharepoint_token_auth"] is CapabilityCheckStatus.FAILED
    assert verdict is CapabilityVerdict.FAILED


@pytest.mark.parametrize(
    ("site_suffixes", "overrides", "check_id"),
    [
        (
            [""],
            {"include_site_documents": False, "include_site_pages": False},
            "sharepoint_content_types",
        ),
        (["", "/../victim"], {}, "sharepoint_configured_sites"),
        (["-does-not-exist"], {}, "sharepoint_configured_sites"),
        (["/No Such Library"], {}, "sharepoint_documents_read"),
        (["/Shared Documents/no-such-folder"], {}, "sharepoint_configured_folder"),
    ],
    ids=[
        "no-content",
        "foreign-host",
        "missing-site",
        "missing-library",
        "missing-folder",
    ],
)
def test_a_wrong_setting_fails_its_check(
    test_secrets: dict[TestSecret, str],
    site_suffixes: list[str],
    overrides: dict[str, Any],
    check_id: str,
) -> None:
    sites = [
        "https://victim.sharepoint.com/sites/x"
        if suffix == "/../victim"
        else _site(suffix)
        for suffix in site_suffixes
    ]

    results, verdict = _run(_credentials(test_secrets), _config(sites, **overrides))

    assert _statuses(results)[check_id] is CapabilityCheckStatus.FAILED
    assert verdict is CapabilityVerdict.FAILED
