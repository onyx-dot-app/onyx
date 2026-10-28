"""Syncs the permissions of the `adls-perm-fixture` container in the
`onyxadlstest` storage account with the CI certificate app, and runs the
permission checks. Read only.

The fixture's root ACL is `user::rwx,group::---,other::--x`. The test user
owns every path and holds Storage Blob Data Owner; the RBAC Readers group
(Subash) holds Storage Blob Data Reader on the container. The table of the
plan lists what each folder and file ACL grants.
"""

from collections.abc import Generator
from typing import Any

import pytest

from ee.onyx.external_permissions.azure_datalake.capability_checks import (
    APP_REGISTRATION_CHECK_ID,
    build_azure_datalake_doc_permission_sync_checks,
    build_azure_datalake_group_sync_checks,
)
from ee.onyx.external_permissions.azure_datalake.group_sync import tenant_groups
from ee.onyx.external_permissions.microsoft_utils.entra_groups import normalize_email
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import SlimDocument
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.usefixtures("enable_ee"),
    pytest.mark.secrets(
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
        TestSecret.ADLS_ACCOUNT_KEY,
    ),
]

ACCOUNT = "onyxadlstest"
CONTAINER = "adls-perm-fixture"
ID_PREFIX = f"azure_datalake:{ACCOUNT}:{CONTAINER}"
RBAC_READERS_GROUP = "d7a184e4-fca0-4d84-97f3-d5b7c718ad6d"
ACL_GROUP_A = "d9d93eee-bfce-46e9-aae1-00623a99b697"
ACL_GROUP_B = "c016e6b3-be0a-4f39-b886-345524716e6f"
TEST_USER = normalize_email("test@danswerai.onmicrosoft.com").lower()
RAUNAK = "raunak@onyx.app"
SUBASH = "subash@onyx.app"

# Path -> readers besides the owner and the RBAC Readers group.
EXTRA_READERS: dict[str, tuple[set[str], set[str]]] = {
    "00-private/private.txt": (set(), set()),
    "10-named-user/named-user.txt": ({RAUNAK}, set()),
    "20-group-a/group-a.txt": (set(), {ACL_GROUP_A}),
    # Traverse through group A and read through group B: Raunak is in both.
    "30-cross-group/cross-group.txt": ({RAUNAK}, set()),
    "40-mask/masked.txt": (set(), set()),
    "55-other-no-traverse/other-blocked.txt": (set(), set()),
    "70-no-traverse/no-traverse.txt": (set(), set()),
    "80-default-only/default-only.txt": (set(), set()),
}
OTHER_READABLE = "50-other/other-readable.txt"
OTHER_MINUS_GROUP_A = "60-other-minus-group/other-minus-group-a.txt"


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


def _provider(credentials: dict[str, Any]) -> OnyxStaticCredentialsProvider:
    return OnyxStaticCredentialsProvider(
        None, DocumentSource.AZURE_DATALAKE, credentials
    )


def _ops(test_secrets: dict[TestSecret, str]) -> AzureDataLakeSourceOperations:
    return AzureDataLakeSourceOperations(
        credentials_provider=_provider(_certificate_credentials(test_secrets)),
        connector_specific_config={
            "account_name": ACCOUNT,
            "container_name": CONTAINER,
        },
    )


def _everyone_group(test_secrets: dict[TestSecret, str]) -> str:
    tenant = test_secrets[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID].strip().lower()
    return f"entra_tenant_everyone:{tenant}"


@pytest.fixture(scope="module")
def synced(
    test_secrets: dict[TestSecret, str],
) -> Generator[dict[str, ExternalAccess], None, None]:
    # A module fixture runs before the function-scoped `enable_ee`.
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    connector = AzureDataLakeConnector(account_name=ACCOUNT, container_name=CONTAINER)
    connector.set_credentials_provider(
        _provider(_certificate_credentials(test_secrets))
    )
    access: dict[str, ExternalAccess] = {}
    for batch in connector.retrieve_all_slim_docs_perm_sync():
        for item in batch:
            if isinstance(item, SlimDocument):
                assert item.external_access is not None
                access[item.id.removeprefix(f"{ID_PREFIX}:")] = item.external_access
    yield access
    if not was_ee:
        global_version.unset_ee()
    fetch_versioned_implementation.cache_clear()


@pytest.mark.parametrize("path", sorted(EXTRA_READERS))
def test_the_sync_mirrors_the_matrix(
    synced: dict[str, ExternalAccess], path: str
) -> None:
    extra_emails, extra_groups = EXTRA_READERS[path]

    access = synced[path]

    assert access.external_user_emails == {TEST_USER} | extra_emails
    assert access.external_user_group_ids == {RBAC_READERS_GROUP} | extra_groups
    assert not access.is_public


def test_other_is_the_tenant_everyone_group(
    synced: dict[str, ExternalAccess], test_secrets: dict[TestSecret, str]
) -> None:
    access = synced[OTHER_READABLE]

    assert access.external_user_group_ids == {_everyone_group(test_secrets)}


def test_other_minus_a_group_is_the_tenant_without_its_members(
    synced: dict[str, ExternalAccess], test_secrets: dict[TestSecret, str]
) -> None:
    access = synced[OTHER_MINUS_GROUP_A]
    (exclusion_group,) = access.external_user_group_ids - {RBAC_READERS_GROUP}

    members = {
        group.id: set(group.user_emails)
        for group in tenant_groups(_ops(test_secrets), {exclusion_group})
    }[exclusion_group]

    assert access.external_user_emails == {TEST_USER}
    assert SUBASH in members
    assert RAUNAK not in members


def test_the_group_sync_reads_the_fixture_groups(
    test_secrets: dict[TestSecret, str],
) -> None:
    groups = {
        group.id: set(group.user_emails)
        for group in tenant_groups(_ops(test_secrets), set())
    }

    assert groups[RBAC_READERS_GROUP] == {SUBASH}
    assert groups[ACL_GROUP_A] == {RAUNAK}
    assert groups[ACL_GROUP_B] == {RAUNAK}
    assert {TEST_USER, RAUNAK, SUBASH} <= groups[_everyone_group(test_secrets)]


def _run_checks(credentials: dict[str, Any]) -> list[CapabilityCheckResult]:
    config: dict[str, Any] = {"account_name": ACCOUNT, "container_name": CONTAINER}
    context = CapabilityCheckContext(
        source=DocumentSource.AZURE_DATALAKE,
        credential_json=credentials,
        connector_specific_config=config,
        source_operations=AzureDataLakeSourceOperations(
            credentials_provider=_provider(credentials),
            connector_specific_config=config,
        ),
    )
    checks: dict[str, CapabilityCheck] = {
        check.check_id: check
        for check in build_azure_datalake_doc_permission_sync_checks()
        + build_azure_datalake_group_sync_checks()
    }
    return run_capability_checks(list(checks.values()), context)


def test_the_permission_checks_pass(test_secrets: dict[TestSecret, str]) -> None:
    results = _run_checks(_certificate_credentials(test_secrets))

    assert {
        result.check_id: result.message
        for result in results
        if result.status is not CapabilityCheckStatus.PASSED
    } == {}


def test_the_account_key_fails_the_app_registration_check(
    test_secrets: dict[TestSecret, str],
) -> None:
    results = _run_checks(
        {
            "authentication_method": "account_key",
            "adls_account_name": ACCOUNT,
            "adls_account_key": test_secrets[TestSecret.ADLS_ACCOUNT_KEY],
        }
    )

    statuses = {result.check_id: result.status for result in results}
    assert statuses[APP_REGISTRATION_CHECK_ID] is CapabilityCheckStatus.FAILED
