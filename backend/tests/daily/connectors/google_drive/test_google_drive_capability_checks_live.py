"""Runs the Google Drive indexing checks against the live test Workspace with
the service account. Read only."""

from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.credential_kinds import resolve_credential_kind
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive.capability_checks import (
    build_google_drive_indexing_checks,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from tests.daily.connectors.google_drive.conftest import build_credentials
from tests.daily.connectors.google_drive.consts_and_utils import (
    ADMIN_EMAIL,
    FOLDER_1_URL,
    SHARED_DRIVE_1_URL,
    TEST_USER_1_EMAIL,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)


def _run(
    test_secrets: dict[TestSecret, str], config: dict[str, Any]
) -> dict[str, CapabilityCheckResult]:
    credential_json = build_credentials(
        ADMIN_EMAIL, oauth=False, test_secrets=test_secrets
    )
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json=credential_json,
        connector_specific_config=config,
        credential_kind=resolve_credential_kind(
            DocumentSource.GOOGLE_DRIVE, credential_json
        ),
        source_operations=GoogleDriveSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.GOOGLE_DRIVE.value, credential_json
            ),
            connector_specific_config=config,
        ),
    )
    results = run_capability_checks(build_google_drive_indexing_checks(), context)
    return {result.check_id: result for result in results}


@pytest.mark.parametrize(
    "config",
    [
        {
            "include_shared_drives": True,
            "include_my_drives": True,
            "include_files_shared_with_me": True,
        },
        {
            "shared_drive_urls": SHARED_DRIVE_1_URL,
            "shared_folder_urls": FOLDER_1_URL,
            "my_drive_emails": TEST_USER_1_EMAIL,
        },
    ],
    ids=["general", "specific"],
)
def test_checks_pass_on_the_test_workspace(
    test_secrets: dict[TestSecret, str], config: dict[str, Any]
) -> None:
    results = _run(test_secrets, config)

    not_passed = {
        check_id: (result.status, result.message)
        for check_id, result in results.items()
        if result.applicable and result.status != CapabilityCheckStatus.PASSED
    }
    assert not not_passed, not_passed
    assert results["google_drive_oauth_user_settings"].applicable is False


def test_misplaced_and_unknown_targets_fail(
    test_secrets: dict[TestSecret, str],
) -> None:
    results = _run(
        test_secrets,
        {
            "shared_folder_urls": SHARED_DRIVE_1_URL,
            "my_drive_emails": "nobody@onyx-test.com",
        },
    )

    folders = results["google_drive_configured_folders"]
    assert folders.status == CapabilityCheckStatus.FAILED
    assert "is a shared drive" in folders.message
    my_drives = results["google_drive_configured_my_drives"]
    assert my_drives.status == CapabilityCheckStatus.FAILED
    assert "nobody@onyx-test.com" in my_drives.message
