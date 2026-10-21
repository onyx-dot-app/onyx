"""The Google Drive checks' rows and the fixes the design asked for: a bad
key is not a delegation problem, an Admin SDK error names the Admin SDK, and a
404 is a clear failure."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import httplib2
import pytest
import requests
from google.auth.exceptions import TransportError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.google_drive.capability_checks import (
    build_google_drive_doc_permission_sync_checks,
    build_google_drive_group_sync_checks,
    build_google_drive_indexing_checks,
)
from onyx.connectors.google_drive.models import GoogleDriveAuth
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    GoogleCredentialKind,
)

_ADMIN = "admin@co.com"
_FOLDER_URL = "https://drive.google.com/drive/folders/{}"


def _listing(*items: Any) -> Any:
    def listing(**_kwargs: Any) -> Iterator[Any]:
        return iter(items)

    return listing


def _ops() -> MagicMock:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.authenticate.return_value = GoogleDriveAuth(
        kind=GoogleCredentialKind.SERVICE_ACCOUNT, primary_admin_email=_ADMIN
    )
    ops.list_files.side_effect = _listing({"id": "f1"})
    ops.list_drives.side_effect = _listing("d1")
    ops.list_user_emails.side_effect = _listing(_ADMIN)
    ops.probe_target.return_value = None
    return ops


def _run(
    check_id: str,
    ops: MagicMock,
    config: dict[str, Any] | None = None,
    form_run: bool = False,
) -> CapabilityCheckResult:
    (check,) = [
        check
        for check in build_google_drive_indexing_checks()
        if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: "{}"},
        connector_specific_config={
            **(config or {}),
            "credential_kind": GoogleCredentialKind.SERVICE_ACCOUNT.value,
        },
        source_operations=ops,
    )
    (result,) = run_capability_checks([check], context, form_run=form_run)
    return result


def test_sign_in_names_who_it_acts_as() -> None:
    assert _run("google_drive_auth", _ops()).summary == f"Acting as {_ADMIN}"


def test_a_deleted_key_is_not_a_delegation_problem() -> None:
    ops = _ops()
    ops.authenticate.side_effect = GoogleDriveRefreshError(
        "invalid_grant: Invalid JWT Signature."
    )

    result = _run("google_drive_auth", ops)

    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Google no longer accepts the account"


def test_an_admin_sdk_error_in_a_drive_probe_names_the_admin_sdk() -> None:
    ops = _ops()
    ops.list_user_emails.side_effect = GoogleDriveHttpError(
        status_code=403,
        reasons=("SERVICE_DISABLED",),
        access_denied=True,
        message="Admin SDK API has not been used",
    )

    result = _run(
        "google_drive_configured_shared_drives",
        ops,
        {"shared_drive_urls": _FOLDER_URL.format("gone")},
    )

    assert result.summary == "Admin SDK API is turned off"


def test_a_404_is_a_clear_failure() -> None:
    ops = _ops()
    ops.get_root_folder_id.side_effect = GoogleDriveHttpError(
        status_code=404, reasons=("notFound",), access_denied=True, message="404"
    )

    result = _run("google_drive_auth", ops)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.INVALID


def test_variants_and_steps_share_a_row() -> None:
    checks = [
        *build_google_drive_indexing_checks(),
        *build_google_drive_doc_permission_sync_checks(),
        *build_google_drive_group_sync_checks(),
    ]
    rows: dict[str, set[str]] = {}
    for check in checks:
        rows.setdefault(check.row_id, set()).add(check.check_id)

    assert rows["google_drive_workspace_users"] == {
        "google_drive_workspace_users",
        "google_drive_user_count",
        "google_drive_directory_users",
    }
    # 19 checks on the 16 rows of the design.
    assert len(checks) == 19
    assert len(rows) == 16
    assert all(len(check.display_name) <= 24 for check in checks)


def _transport_error(cause: Exception) -> TransportError:
    """A token request that got no answer, as google-auth raises it."""
    try:
        raise TransportError(cause) from cause
    except TransportError as error:
        return error


@pytest.mark.parametrize(
    "error",
    [
        _transport_error(requests.ConnectionError("refused")),
        httplib2.ServerNotFoundError("Unable to find the server"),
        ConnectionRefusedError("refused"),
    ],
)
def test_an_unreachable_google_fails_only_a_form_run(error: Exception) -> None:
    ops = _ops()
    ops.authenticate.side_effect = error

    form = _run("google_drive_auth", ops, form_run=True)
    stored = _run("google_drive_auth", ops)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.error_kind == stored.error_kind == CheckErrorKind.UNREACHABLE
    assert form.summary == stored.summary == "Cannot reach Google Drive"


@pytest.mark.parametrize(
    "error",
    [_transport_error(requests.ReadTimeout("read timed out")), TimeoutError()],
)
def test_a_sign_in_timeout_fails_only_a_form_run(error: Exception) -> None:
    ops = _ops()
    ops.list_files.side_effect = error

    form = _run("google_drive_auth", ops, form_run=True)
    stored = _run("google_drive_auth", ops)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.error_kind == stored.error_kind == CheckErrorKind.TIMEOUT
    assert form.summary == "Sign-in timed out"


def test_a_request_timeout_after_sign_in_is_incomplete_on_a_form_run() -> None:
    ops = _ops()
    ops.list_drives.side_effect = TimeoutError()

    result = _run(
        "google_drive_shared_drives",
        ops,
        config={"include_shared_drives": True},
        form_run=True,
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.error_kind == CheckErrorKind.TIMEOUT
    assert result.summary == "Timed out"
