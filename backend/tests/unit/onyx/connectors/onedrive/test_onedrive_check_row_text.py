"""The OneDrive checks' rows: the design's names, short lines and
descriptions, the run order, the partial find of selected users, and what a
check that tested nothing says."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
)
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.onedrive.capability_checks import (
    build_onedrive_doc_permission_sync_checks,
    build_onedrive_group_sync_checks,
    build_onedrive_indexing_checks,
)
from onyx.connectors.onedrive.models import (
    OneDriveDrive,
    OneDriveUser,
    OneDriveUserPage,
)
from onyx.connectors.onedrive.source_operations import OneDriveSourceOperations

_CHECKS: dict[str, CapabilityCheck] = {
    check.check_id: check
    for check in build_onedrive_indexing_checks()
    + build_onedrive_doc_permission_sync_checks()
    + build_onedrive_group_sync_checks()
}
_OWNER = OneDriveUser(
    id="owner-id", user_principal_name="owner@example.com", display_name="Owner"
)


def _gateway() -> MagicMock:
    gateway: MagicMock = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.check_token.return_value = MicrosoftTokenInfo(app_name="Onyx")
    gateway.list_users.return_value = OneDriveUserPage(users=[_OWNER])
    gateway.get_user.return_value = _OWNER
    gateway.get_default_drive.return_value = OneDriveDrive(id="d", name="Documents")
    gateway.get_delta_page.return_value = DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate(
            {"value": [{"id": "item", "name": "a.pdf", "file": {}}]}
        )
    )
    gateway.list_groups.return_value = EntraPage[EntraGroup](
        items=[EntraGroup(id="g", displayName="Engineering")]
    )
    gateway.list_transitive_group_members.return_value = EntraPage[
        EntraDirectoryObject
    ](items=[])
    return gateway


def _run_all(
    check_ids: list[str], gateway: MagicMock, config: dict[str, Any] | None = None
) -> dict[str, CapabilityCheckResult]:
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config=config if config is not None else {},
        source_operations=gateway,
    )
    return {
        result.check_id: result
        for result in run_capability_checks(
            [_CHECKS[check_id] for check_id in check_ids], context
        )
    }


def _run(
    check_id: str, gateway: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, config)[check_id]


def test_the_rows_have_the_design_names() -> None:
    assert {check_id: check.display_name for check_id, check in _CHECKS.items()} == {
        "onedrive_token_auth": "Sign in to Microsoft",
        "onedrive_users": "List users",
        "onedrive_drive_count": "List users",
        "onedrive_configured_users": "Find selected users",
        "onedrive_drive": "Find a OneDrive",
        "onedrive_delta": "Read OneDrive changes",
        "onedrive_item_permissions": "Read file permissions",
        "onedrive_groups": "List groups",
        "onedrive_group_members": "Read group members",
    }
    assert _CHECKS["onedrive_drive_count"].row_id == "onedrive_users"
    assert _CHECKS["onedrive_users"].validates_binding


@pytest.mark.parametrize(
    ("check_id", "summary"),
    [
        ("onedrive_token_auth", "Signed in as Onyx"),
        ("onedrive_users", "Tenant user list is readable"),
        ("onedrive_drive_count", "Up to 1 OneDrive"),
        ("onedrive_drive", "Opened the OneDrive of Owner"),
        ("onedrive_delta", "Read changes in Owner's OneDrive"),
        ("onedrive_item_permissions", "Read permissions of a file in a OneDrive"),
        ("onedrive_groups", "Entra group list is readable"),
        ("onedrive_group_members", "Read members of Engineering"),
    ],
)
def test_a_passing_check_says_what_it_found(check_id: str, summary: str) -> None:
    result = _run(check_id, _gateway())

    assert result.status == CapabilityCheckStatus.PASSED, result.message
    assert result.summary == summary


def test_a_refused_user_listing_names_the_grant() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = MicrosoftGraphError(403, "Authorization", "")

    result = _run("onedrive_users", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No permission to read user directory"


# --- Find selected users ---


def test_all_selected_users_found() -> None:
    result = _run(
        "onedrive_configured_users",
        _gateway(),
        {"users": ["owner@example.com", "b@example.com"]},
    )

    assert result.summary == "All 2 selected users found"


def test_an_entry_that_is_not_an_email_names_it() -> None:
    result = _run("onedrive_configured_users", _gateway(), {"users": ["not-an-email"]})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Not an email address: not-an-email"


def test_blank_entries_say_so() -> None:
    result = _run("onedrive_configured_users", _gateway(), {"users": [" "]})

    assert result.summary == "Users holds only blank entries"


def test_some_missing_users_are_a_partial_find() -> None:
    gateway = _gateway()
    gateway.get_user.side_effect = lambda identifier: (
        _OWNER if identifier == "owner@example.com" else None
    )

    results = _run_all(
        ["onedrive_users", "onedrive_configured_users", "onedrive_drive"],
        gateway,
        {"users": ["owner@example.com", "gone@example.com"]},
    )

    users = results["onedrive_configured_users"]
    assert users.status == CapabilityCheckStatus.INCOMPLETE
    assert users.partial
    assert users.summary == "User not found: gone@example.com"
    assert results["onedrive_drive"].status == CapabilityCheckStatus.PASSED


def test_no_selected_user_found_fails_and_stops_the_drive_check() -> None:
    gateway = _gateway()
    gateway.get_user.return_value = None

    results = _run_all(
        ["onedrive_configured_users", "onedrive_drive"],
        gateway,
        {"users": ["a@example.com", "b@example.com"]},
    )

    assert results["onedrive_configured_users"].summary == "No selected user found"
    assert results["onedrive_drive"].blocked_by == "onedrive_configured_users"


# --- Samples that test nothing ---


def test_no_drive_to_open_is_incomplete() -> None:
    gateway = _gateway()
    gateway.get_default_drive.return_value = None

    result = _run("onedrive_drive", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No OneDrives found to test"


def test_every_drive_refused_names_the_grant() -> None:
    gateway = _gateway()
    gateway.get_default_drive.side_effect = MicrosoftGraphError(403, "accessDenied", "")

    result = _run("onedrive_drive", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No permission to read sampled OneDrives"


def test_an_empty_drive_tests_no_permission_read() -> None:
    gateway = _gateway()
    gateway.get_delta_page.return_value = DriveDeltaFetchResult(page=DriveDeltaPage())

    result = _run("onedrive_item_permissions", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No files found to test"


def test_a_group_that_went_away_is_incomplete() -> None:
    gateway = _gateway()
    gateway.list_transitive_group_members.side_effect = MicrosoftGraphError(
        404, "Request_ResourceNotFound", ""
    )

    result = _run("onedrive_group_members", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Sample group disappeared"


def test_a_refused_group_listing_stops_the_member_check() -> None:
    gateway = _gateway()
    gateway.list_groups.side_effect = MicrosoftGraphError(403, "Authorization", "")

    results = _run_all(["onedrive_groups", "onedrive_group_members"], gateway)

    assert results["onedrive_groups"].summary == "No permission to read Entra groups"
    assert results["onedrive_group_members"].blocked_by == "onedrive_groups"


def test_a_throttled_listing_is_rate_limited() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = MicrosoftGraphError(429, "TooManyRequests", "")

    result = _run("onedrive_users", gateway)

    assert result.error_kind == CheckErrorKind.RATE_LIMITED
    assert result.summary == "Microsoft is throttling requests"
