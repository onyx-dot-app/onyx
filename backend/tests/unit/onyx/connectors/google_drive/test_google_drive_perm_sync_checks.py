"""The Google Drive permission-sync and group-sync checks, against a fake
gateway."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.google_drive.capability_checks import (
    build_google_drive_doc_permission_sync_checks,
    build_google_drive_group_sync_checks,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDirectoryUser,
    GoogleDriveAuth,
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    GoogleCredentialKind,
)
from onyx.db.enums import AccessType

_ADMIN = "admin@co.com"


def _http_error(status: int, *reasons: str) -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=status,
        reasons=reasons,
        access_denied=status in (403, 404),
        message=f"HTTP {status}",
    )


def _listing(*items: Any) -> Any:
    def listing(**_kwargs: Any) -> Iterator[Any]:
        return iter(items)

    return listing


def _ops() -> MagicMock:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.authenticate.return_value = GoogleDriveAuth(
        kind=GoogleCredentialKind.SERVICE_ACCOUNT, primary_admin_email=_ADMIN
    )
    ops.get_admin_user.return_value = GoogleDirectoryUser(
        is_admin=True, is_delegated_admin=False
    )
    ops.list_files.side_effect = _listing(
        {"id": "f1", "permissions": [{"id": "p", "type": "user"}]}
    )
    ops.list_user_emails.side_effect = _listing(_ADMIN)
    ops.list_groups.side_effect = _listing("team@co.com")
    ops.list_group_members.side_effect = _listing()
    ops.list_drives.side_effect = _listing("d1")
    ops.list_drive_members.side_effect = _listing()
    ops.list_folders_with_permissions.side_effect = _listing()
    ops.list_file_permissions.side_effect = _listing({"id": "p"})
    return ops


def _run(check_id: str, ops: MagicMock) -> CapabilityCheckResult:
    (check,) = [
        check
        for check in build_google_drive_doc_permission_sync_checks()
        + build_google_drive_group_sync_checks()
        if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={DB_CREDENTIALS_PRIMARY_ADMIN_KEY: _ADMIN},
        access_type=AccessType.SYNC,
        source_operations=ops,
    )
    (result,) = run_capability_checks([check], context)
    return result


@pytest.mark.parametrize(
    "check_id",
    [
        "google_drive_file_permissions",
        "google_drive_directory_admin",
        "google_drive_directory_users",
        "google_drive_groups",
        "google_drive_shared_drive_members",
        "google_drive_folder_permissions",
    ],
)
def test_checks_pass_for_a_workspace_admin(check_id: str) -> None:
    assert _run(check_id, _ops()).status == CapabilityCheckStatus.PASSED


def test_checks_apply_only_to_permission_synced_connectors() -> None:
    check = build_google_drive_group_sync_checks()[0]

    assert check.access_types is not None
    assert AccessType.PUBLIC not in check.access_types


def test_file_permissions_listed_by_id_are_read() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing({"id": "f1", "permissionIds": ["p"]})

    assert _run("google_drive_file_permissions", ops).status == (
        CapabilityCheckStatus.PASSED
    )
    assert ops.list_file_permissions.call_args.kwargs["file_id"] == "f1"


def test_file_permissions_denied_by_id_fail() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing({"id": "f1", "permissionIds": ["p"]})
    ops.list_file_permissions.side_effect = _http_error(403)

    result = _run("google_drive_file_permissions", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "who can open the file" in result.message


def test_directory_admin_keeps_the_legacy_message() -> None:
    ops = _ops()
    ops.get_admin_user.side_effect = _http_error(403)

    result = _run("google_drive_directory_admin", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert f"Primary admin {_ADMIN} is not authorized" in result.message


def test_admin_sdk_turned_off_is_reported() -> None:
    ops = _ops()
    ops.list_groups.side_effect = _http_error(403, "accessNotConfigured")

    result = _run("google_drive_groups", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Admin SDK API is turned off" in result.message


def test_non_admin_reads_only_its_own_shared_drives() -> None:
    ops = _ops()
    ops.get_admin_user.return_value = GoogleDirectoryUser(
        is_admin=False, is_delegated_admin=False
    )

    result = _run("google_drive_shared_drive_members", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.required is False
    ops.list_drives.assert_called_once_with(
        user_email=_ADMIN, use_domain_admin_access=False
    )


def test_folder_permissions_listed_by_id_are_read() -> None:
    ops = _ops()
    ops.list_folders_with_permissions.side_effect = _listing(
        {"id": "folder", "permissionIds": ["p"]}
    )
    ops.list_file_permissions.side_effect = _listing()

    result = _run("google_drive_folder_permissions", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "no permissions for the folder" in result.message
