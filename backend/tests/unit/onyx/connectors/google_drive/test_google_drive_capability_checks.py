"""The Google Drive indexing checks, against a fake gateway."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckFindingKey,
    CountFinding,
    FindingOption,
    OptionsFinding,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.google_drive.capability_checks import (
    build_google_drive_indexing_checks,
)
from onyx.connectors.google_drive.connector import (
    extract_ids_from_urls,
    extract_str_list_from_comma_str,
)
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.models import (
    GDriveMimeType,
    GoogleDriveAuth,
    GoogleGroupMember,
    GoogleSharedDrive,
)
from onyx.connectors.google_drive.source_operations import (
    ExportSizeThresholdExceeded,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_DICT_TOKEN_KEY,
    MISSING_SCOPES_ERROR_STR,
    GoogleCredentialKind,
)

_DOMAIN = "co.com"
_ADMIN = f"admin@{_DOMAIN}"
_SA = GoogleCredentialKind.SERVICE_ACCOUNT
_OAUTH = GoogleCredentialKind.OAUTH
_FOLDER_URL = "https://drive.google.com/drive/folders/{}"
_SHARED_DRIVES: dict[str, Any] = {"include_shared_drives": True}
_MY_DRIVES: dict[str, Any] = {"include_my_drives": True}
_CREDENTIAL_KEYS = {
    _SA: DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    _OAUTH: DB_CREDENTIALS_DICT_TOKEN_KEY,
}


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
    # The form sets the kind of the picked credential in the config.
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={_CREDENTIAL_KEYS[kind]: "{}"},
        connector_specific_config={**(config or {}), "credential_kind": kind.value},
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
            CapabilityCheckStatus.INCOMPLETE,
            "rate limited",
        ),
        (_http_error(500), CapabilityCheckStatus.INCOMPLETE, "HTTP 500"),
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


def test_service_account_checks_wait_for_the_credential_kind() -> None:
    (check,) = [
        check
        for check in build_google_drive_indexing_checks()
        if check.check_id == "google_drive_workspace_users"
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={},
        connector_specific_config={"include_my_drives": True},
        source_operations=_ops(),
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert "credential_kind" in result.message


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


def test_specific_users_past_the_probe_limit_pass_with_a_count_advisory() -> None:
    emails = [f"user{number}@{_DOMAIN}" for number in range(30)]

    result = _run(
        "google_drive_specific_users",
        _ops(),
        {"include_my_drives": True, "specific_user_emails": ",".join(emails)},
    )

    assert result.status == CapabilityCheckStatus.PASSED
    (advisory,) = result.advisories
    assert "other 5 users" in advisory.message
    assert _DOMAIN not in advisory.message


def test_specific_users_within_the_probe_limit_have_no_advisory() -> None:
    result = _run(
        "google_drive_specific_users",
        _ops(),
        {"include_my_drives": True, "specific_user_emails": _ADMIN},
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.advisories == []


def test_oauth_reports_ignored_per_user_settings() -> None:
    result = _run(
        "google_drive_oauth_user_settings",
        _ops(_OAUTH),
        {"my_drive_emails": f"user@{_DOMAIN}"},
        kind=_OAUTH,
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "My Drive emails" in result.message


def test_no_shared_drive_passes_with_an_advisory() -> None:
    result = _run("google_drive_shared_drives", _ops(), {"include_shared_drives": True})

    assert result.status == CapabilityCheckStatus.PASSED
    (advisory,) = result.advisories
    assert "did not verify" in advisory.message


def test_visible_shared_drive_passes_without_an_advisory() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run("google_drive_shared_drives", ops, {"include_shared_drives": True})

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.advisories == []


def test_shared_drives_list_with_domain_admin_access_for_a_service_account() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run("google_drive_shared_drives", ops, {"include_shared_drives": True})

    assert result.status == CapabilityCheckStatus.PASSED
    ops.list_drives.assert_called_once_with(
        user_email=_ADMIN, use_domain_admin_access=True
    )


def test_configured_shared_drive_that_nobody_sees_is_a_partial_find() -> None:
    """Some selected drives found: INCOMPLETE, and later checks run on them."""
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {
            "shared_drive_urls": f"{_FOLDER_URL.format('d1')},{_FOLDER_URL.format('gone')}"
        },
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.partial
    assert result.summary == "1 of 2 selected drives not found"
    assert result.description is not None
    assert "gone" in result.description
    assert "d1" not in result.description


def test_configured_shared_drives_that_nobody_sees_fail() -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("d1")

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {"shared_drive_urls": _FOLDER_URL.format("gone")},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No selected drive found"


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


def test_configured_shared_drive_id_that_is_a_file_fails() -> None:
    ops = _ops()
    ops.probe_target.return_value = {"id": "file1", "mimeType": "text/plain"}

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {"shared_drive_urls": _FOLDER_URL.format("file1")},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "file1" in result.message


@pytest.mark.parametrize(
    ("folder_id", "summary"),
    [
        ("drive1", "A selected folder is a shared drive"),
        ("file1", "A selected folder URL is a file"),
    ],
)
def test_a_configured_folder_that_is_no_folder_fails(
    folder_id: str, summary: str
) -> None:
    ops = _ops()
    ops.list_drives.side_effect = _listing("drive1")

    def probe_target(*, user_email: str, target_id: str) -> dict[str, Any] | None:  # noqa: ARG001
        if target_id == "file1":
            return {"id": target_id, "mimeType": "application/pdf"}
        return None

    ops.probe_target.side_effect = probe_target

    result = _run(
        "google_drive_configured_folders",
        ops,
        {"shared_folder_urls": _FOLDER_URL.format(folder_id)},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == summary


def test_configured_folders_some_unseen_are_a_partial_find() -> None:
    ops = _ops()

    def probe_target(*, user_email: str, target_id: str) -> dict[str, Any] | None:  # noqa: ARG001
        if target_id == "folder1":
            return {"id": target_id, "mimeType": DRIVE_FOLDER_TYPE}
        return None

    ops.probe_target.side_effect = probe_target
    urls = ",".join(_FOLDER_URL.format(i) for i in ("folder1", "gone"))

    result = _run("google_drive_configured_folders", ops, {"shared_folder_urls": urls})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "1 of 2 selected folders not found"


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


@pytest.mark.parametrize(("user_count", "unprobed"), [(30, 5), (25, 0)])
def test_my_drives_past_the_probe_limit_pass_with_a_count_advisory(
    user_count: int, unprobed: int
) -> None:
    emails = [f"user{number}@{_DOMAIN}" for number in range(user_count)]
    ops = _ops()
    ops.list_user_emails.side_effect = _listing(*emails)

    result = _run(
        "google_drive_configured_my_drives", ops, {"my_drive_emails": ",".join(emails)}
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert ops.get_root_folder_id.call_count == 25
    if unprobed == 0:
        assert result.advisories == []
        return
    (advisory,) = result.advisories
    assert f"other {unprobed} users" in advisory.message
    assert _DOMAIN not in advisory.message


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

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Sampled file blocks downloads"
    assert "blocked downloads" in result.message


def test_docs_api_turned_off_is_reported() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing(_file("doc", GDriveMimeType.DOC.value))
    ops.fetch_google_doc.side_effect = _http_error(403, "SERVICE_DISABLED")

    result = _run("google_drive_docs_api", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Google Docs API is turned off" in result.message


def test_docs_api_names_the_drive_api_when_the_listing_fails() -> None:
    ops = _ops()
    ops.list_files.side_effect = _http_error(403, "SERVICE_DISABLED")

    result = _run("google_drive_docs_api", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Google Drive API is turned off" in result.message
    ops.fetch_google_doc.assert_not_called()


def test_docs_api_is_incomplete_without_a_google_doc() -> None:
    ops = _ops()
    ops.list_files.side_effect = _listing()

    result = _run("google_drive_docs_api", ops)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No Google Docs found to test"
    ops.fetch_google_doc.assert_not_called()


# google_drive_shared_drive_listing


def test_shared_drive_listing_offers_each_drive_url_for_the_field() -> None:
    ops = _ops()
    ops.list_named_drives.side_effect = _listing(
        GoogleSharedDrive(id="d1", name="Engineering"),
        GoogleSharedDrive(id="d2", name=""),
    )

    result = _run("google_drive_shared_drive_listing", ops, _SHARED_DRIVES)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.findings == [
        OptionsFinding(
            key=CheckFindingKey.SHARED_DRIVES,
            field_name="shared_drive_urls",
            options=[
                FindingOption(value=_FOLDER_URL.format("d1"), label="Engineering"),
                FindingOption(value=_FOLDER_URL.format("d2"), label="d2"),
            ],
        )
    ]
    ops.list_named_drives.assert_called_once_with(
        user_email=_ADMIN, use_domain_admin_access=True
    )


@pytest.mark.parametrize(
    "config, applies",
    [
        ({"include_shared_drives": True}, True),
        ({"shared_drive_urls": _FOLDER_URL.format("d1")}, True),
        ({"include_my_drives": True}, False),
        ({"include_files_shared_with_me": True}, False),
        # A specific request turns the general toggles off.
        ({"include_shared_drives": True, "my_drive_emails": _ADMIN}, False),
    ],
    ids=[
        "shared-drives",
        "shared-drive-urls",
        "my-drives-only",
        "shared-with-me-only",
        "specific-request-without-drives",
    ],
)
def test_shared_drive_listing_applies_only_when_shared_drives_are_indexed(
    config: dict[str, Any], applies: bool
) -> None:
    ops = _ops()
    ops.list_named_drives.side_effect = _listing(GoogleSharedDrive(id="d1", name="A"))

    result = _run("google_drive_shared_drive_listing", ops, config)

    assert result.applicable is applies
    if applies:
        assert result.findings
    else:
        assert result.status == CapabilityCheckStatus.SKIPPED
        assert result.findings == []
        ops.list_named_drives.assert_not_called()


def test_shared_drive_listing_values_parse_back_to_the_drive_ids() -> None:
    ops = _ops()
    ops.list_named_drives.side_effect = _listing(GoogleSharedDrive(id="d1", name="A"))

    (finding,) = _run("google_drive_shared_drive_listing", ops, _SHARED_DRIVES).findings

    assert isinstance(finding, OptionsFinding)
    urls = ",".join(option.value for option in finding.options)
    assert extract_ids_from_urls(extract_str_list_from_comma_str(urls)) == ["d1"]


def test_shared_drive_listing_lists_as_the_oauth_user() -> None:
    ops = _ops(_OAUTH)
    ops.list_named_drives.side_effect = _listing()

    result = _run("google_drive_shared_drive_listing", ops, _SHARED_DRIVES, kind=_OAUTH)

    assert result.status == CapabilityCheckStatus.PASSED
    ops.list_named_drives.assert_called_once_with(
        user_email=_ADMIN, use_domain_admin_access=False
    )


def test_shared_drive_listing_stops_at_the_option_cap() -> None:
    ops = _ops()
    ops.list_named_drives.side_effect = lambda **_: (
        GoogleSharedDrive(id=f"d{number}", name=f"Drive {number}")
        for number in range(5000)
    )

    (finding,) = _run("google_drive_shared_drive_listing", ops, _SHARED_DRIVES).findings

    assert isinstance(finding, OptionsFinding)
    assert len(finding.options) == MAX_FINDING_OPTIONS
    assert finding.truncated is True


def test_shared_drive_listing_403_fails_and_leaves_the_verdict_alone() -> None:
    ops = _ops()
    ops.list_named_drives.side_effect = _http_error(403)

    result = _run("google_drive_shared_drive_listing", ops, _SHARED_DRIVES)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "cannot list the shared drives" in result.message
    assert result.discovery is True
    assert result.required is False


# google_drive_user_count


def test_user_count_counts_the_listed_users() -> None:
    result = _run("google_drive_user_count", _ops(), _MY_DRIVES)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.findings == [
        CountFinding(key=CheckFindingKey.VISIBLE_ORGANIZATION_USERS, count=2)
    ]


def test_user_count_stops_at_the_cap() -> None:
    ops = _ops()
    ops.list_user_emails.side_effect = lambda **_: (
        f"user{number}@{_DOMAIN}" for number in range(5000)
    )

    result = _run("google_drive_user_count", ops, _MY_DRIVES)

    assert result.findings == [
        CountFinding(
            key=CheckFindingKey.VISIBLE_ORGANIZATION_USERS,
            count=MAX_FINDING_OPTIONS,
            at_least=True,
        )
    ]


@pytest.mark.parametrize(
    "config, kind, applies",
    [
        (_MY_DRIVES, _SA, True),
        ({**_MY_DRIVES, "include_shared_drives": True}, _SA, True),
        ({"include_shared_drives": True}, _SA, False),
        ({"include_files_shared_with_me": True}, _SA, False),
        ({**_MY_DRIVES, "specific_user_emails": _ADMIN}, _SA, False),
        ({**_MY_DRIVES, "my_drive_emails": _ADMIN}, _SA, False),
        (_MY_DRIVES, _OAUTH, False),
    ],
    ids=[
        "my-drives",
        "my-and-shared-drives",
        "shared-drives-only",
        "shared-with-me-only",
        "specific-users",
        "specific-my-drives",
        "oauth",
    ],
)
def test_user_count_applies_only_when_every_my_drive_is_indexed(
    config: dict[str, Any], kind: GoogleCredentialKind, applies: bool
) -> None:
    result = _run("google_drive_user_count", _ops(kind), config, kind=kind)

    assert result.applicable is applies
    if not applies:
        assert result.status == CapabilityCheckStatus.SKIPPED
        assert result.findings == []


def test_user_count_403_fails_and_leaves_the_verdict_alone() -> None:
    ops = _ops()
    ops.list_user_emails.side_effect = _http_error(403)

    result = _run("google_drive_user_count", ops, _MY_DRIVES)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.discovery is True
    assert result.required is False


def test_discovery_checks_are_the_listing_and_the_count() -> None:
    assert {
        check.check_id
        for check in build_google_drive_indexing_checks()
        if check.discovery
    } == {"google_drive_shared_drive_listing", "google_drive_user_count"}


@pytest.mark.parametrize(
    "check_id", ["google_drive_specific_users", "google_drive_configured_my_drives"]
)
def test_a_failed_sign_in_stops_the_selected_user_checks(check_id: str) -> None:
    ops = _ops()
    ops.list_files.side_effect = _http_error(401)
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={_CREDENTIAL_KEYS[_SA]: "{}"},
        connector_specific_config={
            "include_my_drives": True,
            "specific_user_emails": _ADMIN,
            "my_drive_emails": _ADMIN,
            "credential_kind": _SA.value,
        },
        source_operations=ops,
    )

    results = run_capability_checks(build_google_drive_indexing_checks(), context)

    (result,) = [result for result in results if result.check_id == check_id]
    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.blocked_by == "google_drive_auth"
    ops.get_root_folder_id.assert_not_called()


def test_a_rate_limit_names_the_status_google_sent() -> None:
    ops = _ops()
    ops.list_files.side_effect = _http_error(403, "userRateLimitExceeded")

    result = _run("google_drive_auth", ops)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.description is not None
    assert "(HTTP 403)" in result.description
