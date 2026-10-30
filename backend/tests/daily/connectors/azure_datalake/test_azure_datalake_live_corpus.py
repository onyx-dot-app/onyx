"""Indexes the fixed Azure Data Lake corpus in the `onyxadlstest` storage
account of the test tenant, with the CI certificate app and with the account
key, and runs the indexing checks. Read only.

The corpus is built by an untracked provisioning script; its layout is below.
"""

import time
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake import connector as connector_module
from onyx.connectors.azure_datalake.capability_checks import (
    CONTAINER_CHECK_ID,
    PATH_PREFIX_CHECK_ID,
    build_azure_datalake_indexing_checks,
)
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import SlimDocument
from tests.daily.connectors.utils import ConnectorOutput, load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.usefixtures("mock_get_unstructured_api_key"),
    pytest.mark.secrets(
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
        TestSecret.ADLS_ACCOUNT_KEY,
        TestSecret.TEAMS_APPLICATION_ID,
        TestSecret.TEAMS_DIRECTORY_ID,
        TestSecret.TEAMS_SECRET,
    ),
]

ACCOUNT = "onyxadlstest"
INDEX_CONTAINER = "adls-index-fixture"
PERM_CONTAINER = "adls-perm-fixture"
ID_PREFIX = f"azure_datalake:{ACCOUNT}:{INDEX_CONTAINER}"
# Images are off, so `images/square.png` is not indexed; the over-size and
# unsupported files under `filters/` never are.
EXPECTED_PATHS = {
    "data/table.csv",
    "docs/guide.md",
    "docs/nested/deep/notes.txt",
    "docs/page.html",
    "docs/readme.txt",
    "office/report.docx",
    "office/sheet.xlsx",
    *(f"paging/file_{index:03d}.txt" for index in range(25)),
}
EXPECTED_DIRECTORIES = {
    "data",
    "docs",
    "docs/nested",
    "docs/nested/deep",
    "empty-dir",
    "filters",
    "images",
    "office",
    "paging",
}
KEYWORDS = {
    "docs/readme.txt": "azurite-lantern",
    "docs/guide.md": "cobalt-harbor",
    "docs/page.html": "silver-meadow",
    "docs/nested/deep/notes.txt": "quiet-fjord",
    "office/report.docx": "ember-atlas",
}


def _certificate_credentials(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "authentication_method": "certificate",
        "adls_client_id": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        "adls_directory_id": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
        "adls_private_key": test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        "adls_certificate_password": test_secrets[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
    }


def _account_key_credentials(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "authentication_method": "account_key",
        "adls_account_name": ACCOUNT,
        "adls_account_key": test_secrets[TestSecret.ADLS_ACCOUNT_KEY],
    }


def _no_role_credentials(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    """An app of the tenant with no role on the storage account."""
    return {
        "authentication_method": "client_secret",
        "adls_client_id": test_secrets[TestSecret.TEAMS_APPLICATION_ID],
        "adls_directory_id": test_secrets[TestSecret.TEAMS_DIRECTORY_ID],
        "adls_client_secret": test_secrets[TestSecret.TEAMS_SECRET],
    }


def _provider(credentials: dict[str, Any]) -> OnyxStaticCredentialsProvider:
    return OnyxStaticCredentialsProvider(
        None, DocumentSource.AZURE_DATALAKE, credentials
    )


def _index(credentials: dict[str, Any], container: str) -> ConnectorOutput:
    connector = AzureDataLakeConnector(account_name=ACCOUNT, container_name=container)
    connector.set_credentials_provider(_provider(credentials))
    return load_all_from_connector(connector, 0, time.time())


def _run_checks(credentials: dict[str, Any]) -> list[CapabilityCheckResult]:
    config: dict[str, Any] = {
        "account_name": ACCOUNT,
        "container_name": INDEX_CONTAINER,
        "path_prefix": "docs",
    }
    context = CapabilityCheckContext(
        source=DocumentSource.AZURE_DATALAKE,
        credential_json=credentials,
        connector_specific_config=config,
        source_operations=AzureDataLakeSourceOperations(
            credentials_provider=_provider(credentials),
            connector_specific_config=config,
        ),
    )
    return run_capability_checks(build_azure_datalake_indexing_checks(), context)


def _not_passed(results: list[CapabilityCheckResult]) -> dict[str, str | None]:
    return {
        result.check_id: result.message
        for result in results
        if result.status
        not in (CapabilityCheckStatus.PASSED, CapabilityCheckStatus.SKIPPED)
    }


def test_the_app_indexes_the_corpus_page_by_page(
    test_secrets: dict[TestSecret, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connector_module, "PAGE_SIZE", 4)

    output = _index(_certificate_credentials(test_secrets), INDEX_CONTAINER)

    documents = {document.id: document for document in output.documents}
    assert set(documents) == {f"{ID_PREFIX}:{path}" for path in EXPECTED_PATHS}
    for path, keyword in KEYWORDS.items():
        text = " ".join(
            section.text or "" for section in documents[f"{ID_PREFIX}:{path}"].sections
        )
        assert keyword in text, path
    directories = {
        node.raw_node_id for node in output.hierarchy_nodes if node.raw_parent_id
    }
    assert directories == {f"{ID_PREFIX}:{path}" for path in EXPECTED_DIRECTORIES}


def test_the_account_key_indexes_what_the_slim_listing_lists(
    test_secrets: dict[TestSecret, str],
) -> None:
    credentials = _account_key_credentials(test_secrets)
    connector = AzureDataLakeConnector(
        account_name=ACCOUNT, container_name=INDEX_CONTAINER
    )
    connector.set_credentials_provider(_provider(credentials))

    output = load_all_from_connector(connector, 0, time.time())
    slim_ids = {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }

    assert {document.id for document in output.documents} == slim_ids
    assert slim_ids == {f"{ID_PREFIX}:{path}" for path in EXPECTED_PATHS}


def test_the_data_reader_role_reads_files_that_acls_deny(
    test_secrets: dict[TestSecret, str],
) -> None:
    output = _index(_certificate_credentials(test_secrets), PERM_CONTAINER)

    assert len(output.documents) == 10


@pytest.mark.parametrize(
    "credentials_of",
    [_certificate_credentials, _account_key_credentials],
    ids=["certificate-app", "account-key"],
)
def test_the_indexing_checks_pass(
    test_secrets: dict[TestSecret, str], credentials_of: Any
) -> None:
    results = _run_checks(credentials_of(test_secrets))

    assert _not_passed(results) == {}


def test_an_app_without_a_role_fails_the_path_prefix_check(
    test_secrets: dict[TestSecret, str],
) -> None:
    results = _run_checks(_no_role_credentials(test_secrets))

    statuses = {result.check_id: result.status for result in results}
    # With a path prefix, a closed root leaves the decision to the prefix.
    assert statuses[CONTAINER_CHECK_ID] is CapabilityCheckStatus.PASSED
    assert statuses[PATH_PREFIX_CHECK_ID] is CapabilityCheckStatus.FAILED
