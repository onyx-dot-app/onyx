"""The Google Drive indexing checks, against a fake gateway."""

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
    build_google_drive_indexing_checks,
)
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    ExportSizeThresholdExceeded,
    GoogleDriveAuth,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
    GoogleGroupMember,
)
from onyx.connectors.google_utils.shared_constants import (
    MISSING_SCOPES_ERROR_STR,
    GoogleCredentialKind,
)

_DOMAIN = "co.com"
_ADMIN = f"admin@{_DOMAIN}"
_SA = GoogleCredentialKind.SERVICE_ACCOUNT
_OAUTH = GoogleCredentialKind.OAUTH
_FOLDER_URL = "https://drive.google.com/drive/folders/{}"


def _http_error(status: int, *reasons: str) -> GoogleDriveHttpError:
    rate_limited = "userRateLimitExceeded" in reasons
    return GoogleDriveHttpError(
        status_code=status,
        reasons=reasons,
        access_denied=status in (403, 404) and not rate_limited,
        message=f"HTTP {status} {reasons}",
    )


def _file(
    file_id: str, mime_type: str = "text/plain", size: int = 10
) -> dict[str, Any]:
    return {"id": file_id, "name": file_id, "mimeType": mime_type, "size": str(size)}


def _listing(*items: Any) -> Any:
    def listing(**_kwargs: Any) -> Iterator[Any]:
        return iter(items)

    return listing


def _ops(kind: GoogleCredentialKind = _SA) -> MagicMock:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.authenticate.return_value = GoogleDriveAuth(
        kind=kind, primary_admin_email=_ADMIN
    )
    ops.list_files.side_effect = _listing(_file("f1"))
    ops.list_drives.side_effect = _listing()
    ops.list_user_emails.side_effect = _listing(_ADMIN, f"user@{_DOMAIN}")
    ops.probe_target.return_value = None
    return ops


def _run(
    check_id: str,
    ops: MagicMock,
    config: dict[str, Any] | None = None,
    kind: GoogleCredentialKind = _SA,
) -> CapabilityCheckResult:
    (check,) = [
        check
        for check in build_google_drive_indexing_checks()
        if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={},
        connector_specific_config=config,
        credential_kind=kind.value,
        source_operations=ops,
    )
    (result,) = run_capability_checks([check], context)
    return result


def test_auth_passes_and_opens_the_admin_my_drive() -> None:
    ops = _ops()

    result = _run("google_drive_auth", ops)

    assert result.status == CapabilityCheckStatus.PASSED
    ops.get_root_folder_id.assert_called_once_with(user_email=_ADMIN)


@pytest.mark.parametrize(
    "error,status,phrase",
    [
        (
            GoogleDriveRefreshError(f"unauthorized_client: {MISSING_SCOPES_ERROR_STR}"),
            CapabilityCheckStatus.FAILED,
            "Domain-wide",
        ),
        (
            GoogleDriveRefreshError("invalid_grant: Invalid email or User ID"),
            CapabilityCheckStatus.FAILED,
            "act as",
        ),
        (_http_error(401), CapabilityCheckStatus.FAILED, "HTTP 401"),
        (
            _http_error(403, "accessNotConfigured"),
            CapabilityCheckStatus.FAILED,
            "Google Drive API is turned off",
        ),
        (
            _http_error(403, "userRateLimitExceeded"),
            CapabilityCheckStatus.INDETERMINATE,
            "rate limited",
        ),
        (_http_error(500), CapabilityCheckStatus.INDETERMINATE, "HTTP 500"),
    ],
)
def test_auth_explains_each_failure(
    error: Exception, status: CapabilityCheckStatus, phrase: str
) -> None:
    ops = _ops()
    ops.list_files.side_effect = error

    result = _run("google_drive_auth", ops)

    assert result.status == status
    assert phrase in result.message


def test_revoked_oauth_grant_is_an_expired_credential() -> None:
    ops = _ops(_OAUTH)
    ops.authenticate.side_effect = GoogleDriveRefreshError("invalid_grant")

    result = _run("google_drive_auth", ops, kind=_OAUTH)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "CredentialExpiredError"


def test_service_account_checks_do_not_apply_to_oauth() -> None:
    result = _run("google_drive_workspace_users", _ops(_OAUTH), kind=_OAUTH)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable is False


def test_workspace_users_denied_names_the_admin_requirement() -> None:
    ops = _ops()
    ops.list_user_emails.side_effect = _http_error(403)

    result = _run("google_drive_workspace_users", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "cannot list the Workspace users" in result.message


def test_workspace_users_do_not_apply_with_specific_users() -> None:
    result = _run(
        "google_drive_workspace_users",
        _ops(),
        {"include_my_drives": True, "specific_user_emails": _ADMIN},
    )

    assert result.applicable is False


def test_specific_users_reports_the_users_onyx_cannot_act_as() -> None:
    ops = _ops()
    bad_user = f"typo@{_DOMAIN}"

    def get_root_folder_id(*, user_email: str) -> str:
        if user_email == bad_user:
            raise GoogleDriveRefreshError("invalid_grant")
        return "root"

    ops.get_root_folder_id.side_effect = get_root_folder_id

    result = _run(
        "google_drive_specific_users",
        ops,
        {"include_my_drives": True, "specific_user_emails": f"{_ADMIN},{bad_user}"},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.required is False
    assert bad_user in result.message
    assert _ADMIN not in result.message


def test_oauth_reports_ignored_per_user_settings() -> None:
    result = _run(
        "google_drive_oauth_user_settings",
        _ops(_OAUTH),
        {"my_drive_emails": f"user@{_DOMAIN}"},
        kind=_OAUTH,
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "My Drive emails" in result.message


def test_no_shared_drive_is_indeterminate_not_failed() -> None:
    result = _run("google_drive_shared_drives", _ops(), {"include_shared_drives": True})

    assert result.status == CapabilityCheckStatus.INDETERMINATE


def test_shared_drives_list_with_domain_admin_access_for_a_service_account() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run("google_drive_shared_drives", ops, {"include_shared_drives": True})

    assert result.status == CapabilityCheckStatus.PASSED
    ops.list_drives.assert_called_once_with(
        user_email=_ADMIN, use_domain_admin_access=True
    )


def test_configured_shared_drive_that_nobody_sees_fails() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {
            "shared_drive_urls": f"{_FOLDER_URL.format('d1')},{_FOLDER_URL.format('gone')}"
        },
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "gone" in result.message
    assert "d1" not in result.message


def test_configured_shared_drive_id_that_is_a_visible_folder_passes() -> None:
    ops = _ops()

    def probe_target(*, user_email: str, target_id: str) -> dict[str, Any] | None:
        if user_email == f"user@{_DOMAIN}":
            return {"id": target_id, "mimeType": DRIVE_FOLDER_TYPE}
        return None

    ops.probe_target.side_effect = probe_target

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {"shared_drive_urls": _FOLDER_URL.format("folder1")},
    )

    assert result.status == CapabilityCheckStatus.PASSED


def test_configured_folders_report_each_problem() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("drive1")

    def probe_target(*, user_email: str, target_id: str) -> dict[str, Any] | None:  # noqa: ARG001
        if target_id == "file1":
            return {"id": target_id, "mimeType": "application/pdf"}
        return None

    ops.probe_target.side_effect = probe_target
    urls = ",".join(_FOLDER_URL.format(i) for i in ("drive1", "file1", "gone"))

    result = _run("google_drive_configured_folders", ops, {"shared_folder_urls": urls})

    assert result.status == CapabilityCheckStatus.FAILED
    assert "drive1 is a shared drive" in result.message
    assert "file1 is a file" in result.message
    assert "gone is not visible" in result.message


def test_configured_folder_is_listed_as_its_viewer() -> None:
    ops = _ops()
    ops.probe_target.return_value = {"id": "folder1", "mimeType": DRIVE_FOLDER_TYPE}

    result = _run(
        "google_drive_configured_folders",
        ops,
        {"shared_folder_urls": _FOLDER_URL.format("folder1")},
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert ops.list_files.call_args.kwargs["user_email"] == _ADMIN
    assert "'folder1' in parents" in ops.list_files.call_args.kwargs["query"]


def test_my_drive_alias_is_reported_as_skipped() -> None:
    result = _run(
        "google_drive_configured_my_drives",
        _ops(),
        {"my_drive_emails": f"alias@{_DOMAIN}"},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert f"alias@{_DOMAIN}" in result.message


def test_my_drive_of_a_listed_user_passes() -> None:
    ops = _ops()

    result = _run(
        "google_drive_configured_my_drives",
        ops,
        {"my_drive_emails": f"USER@{_DOMAIN}"},
    )

    assert result.status == CapabilityCheckStatus.PASSED
    ops.get_root_folder_id.assert_called_once_with(user_email=f"USER@{_DOMAIN}")


def _drive_with_members(ops: MagicMock, *members: dict[str, str]) -> None:
    ops.list_drives.side_effect = _listing("d1")
    ops.list_drive_members.side_effect = _listing(*members)
    ops.can_list_drive.return_value = True


def test_organizer_reached_through_a_group_passes() -> None:
    ops = _ops()
    _drive_with_members(
        ops, {"emailAddress": f"team@{_DOMAIN}", "type": "group", "role": "organizer"}
    )
    ops.list_group_members.side_effect = _listing(
        GoogleGroupMember(email=f"boss@{_DOMAIN}", type="USER")
    )

    result = _run(
        "google_drive_shared_drive_organizer", ops, {"include_shared_drives": True}
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert ops.list_files.call_args.kwargs["user_email"] == f"boss@{_DOMAIN}"


def test_drive_without_an_organizer_warns() -> None:
    ops = _ops()
    _drive_with_members(
        ops, {"emailAddress": f"reader@{_DOMAIN}", "type": "user", "role": "reader"}
    )

    result = _run(
        "google_drive_shared_drive_organizer", ops, {"include_shared_drives": True}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.required is False
    assert "limited access" in result.message


def test_content_read_exports_a_native_file_and_downloads_an_upload() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing(
        _file("doc", GDriveMimeType.DOC.value), _file("big", size=10**9), _file("small")
    )

    result = _run("google_drive_content_read", ops)

    assert result.status == CapabilityCheckStatus.PASSED
    assert ops.export_file.call_args.kwargs["file_id"] == "doc"
    assert ops.download_file.call_args.kwargs["file_id"] == "small"


def test_content_read_passes_on_a_file_over_the_probe_size() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing(_file("doc", GDriveMimeType.DOC.value))
    ops.export_file.side_effect = ExportSizeThresholdExceeded("big")

    assert _run("google_drive_content_read", ops).status == CapabilityCheckStatus.PASSED


def test_content_read_explains_a_download_blocked_by_the_owner() -> None:
    ops = _ops()
    ops.download_file.side_effect = _http_error(403, "cannotDownloadFile")

    result = _run("google_drive_content_read", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "blocked downloads" in result.message


def test_docs_api_turned_off_is_reported() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing(_file("doc", GDriveMimeType.DOC.value))
    ops.fetch_google_doc.side_effect = _http_error(403, "SERVICE_DISABLED")

    result = _run("google_drive_docs_api", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Google Docs API is turned off" in result.message


def test_docs_api_passes_without_a_google_doc() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing()

    assert _run("google_drive_docs_api", ops).status == CapabilityCheckStatus.PASSED
    ops.fetch_google_doc.assert_not_called()
