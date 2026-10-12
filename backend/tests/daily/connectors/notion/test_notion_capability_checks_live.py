"""Runs the Notion capability checks against the live test workspace (the
onyx-test.com integration). Read only."""

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
from onyx.connectors.notion.capability_checks import build_notion_indexing_checks
from onyx.connectors.notion.models import NotionSearchObjectType
from onyx.connectors.notion.source_operations import NotionSourceOperations
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.NOTION_INTEGRATION_TOKEN)

_ROOT_PAGE_TITLE = "Root"
# A well-formed page ID that no workspace shares with the integration.
_UNKNOWN_PAGE_ID = "00000000-0000-4000-8000-000000000000"


def _credential(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "notion_integration_token": test_secrets[
            TestSecret.NOTION_INTEGRATION_TOKEN
        ].strip()
    }


def _gateway(credential_json: dict[str, Any]) -> NotionSourceOperations:
    return NotionSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.NOTION.value, credential_json
        )
    )


def _results(
    credential_json: dict[str, Any], config: dict[str, Any]
) -> dict[str, CapabilityCheckResult]:
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json=credential_json,
        connector_specific_config=config,
        source_operations=_gateway(credential_json),
    )
    results: list[CapabilityCheckResult] = run_capability_checks(
        build_notion_indexing_checks(), context
    )
    return {result.check_id: result for result in results}


def _title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(text["plain_text"] for text in prop["title"]).strip()
    return ""


def _root_page_id(credential_json: dict[str, Any]) -> str:
    for search_page in _gateway(credential_json).iter_search(
        object_type=NotionSearchObjectType.PAGE
    ):
        for page in search_page.results:
            if _title(page) == _ROOT_PAGE_TITLE:
                return str(page["id"])
    raise AssertionError(f"The test workspace has no page '{_ROOT_PAGE_TITLE}'.")


def _assert_indexing_passes(by_id: dict[str, CapabilityCheckResult]) -> None:
    failures: dict[str, str] = {
        check_id: result.message
        for check_id, result in by_id.items()
        if result.applicable and result.status != CapabilityCheckStatus.PASSED
    }
    assert not failures, failures
    verdicts: dict[CredentialCapability, CapabilityVerdict] = (
        compute_capability_verdicts(
            {CredentialCapability.INDEXING}, list(by_id.values())
        )
    )
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.PASSED


def test_indexing_checks_pass_for_every_shared_page(
    test_secrets: dict[TestSecret, str],
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(_credential(test_secrets), {})

    _assert_indexing_passes(by_id)
    assert by_id["notion_shared_content"].status == CapabilityCheckStatus.PASSED
    assert not by_id["notion_root_page"].applicable


def test_indexing_checks_pass_for_a_root_page(
    test_secrets: dict[TestSecret, str],
) -> None:
    credential_json: dict[str, Any] = _credential(test_secrets)

    by_id: dict[str, CapabilityCheckResult] = _results(
        credential_json, {"root_page_id": _root_page_id(credential_json)}
    )

    _assert_indexing_passes(by_id)
    assert by_id["notion_root_page"].status == CapabilityCheckStatus.PASSED
    assert not by_id["notion_shared_content"].applicable


def test_root_page_fails_for_a_page_that_is_not_shared(
    test_secrets: dict[TestSecret, str],
) -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        _credential(test_secrets), {"root_page_id": _UNKNOWN_PAGE_ID}
    )

    result: CapabilityCheckResult = by_id["notion_root_page"]
    assert result.status == CapabilityCheckStatus.FAILED, result.message
    assert result.error_type == "ConnectorValidationError"


def test_auth_fails_for_a_wrong_token() -> None:
    by_id: dict[str, CapabilityCheckResult] = _results(
        {"notion_integration_token": "ntn_not_a_real_token"}, {}
    )

    result: CapabilityCheckResult = by_id["notion_auth"]
    assert result.status == CapabilityCheckStatus.FAILED, result.message
    assert result.error_type == "CredentialExpiredError"
