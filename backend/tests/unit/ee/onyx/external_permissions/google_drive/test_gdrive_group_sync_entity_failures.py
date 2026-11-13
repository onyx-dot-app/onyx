"""Drive group sync skips a user or Google group it cannot read whole, reports
it as a SyncEntityFailure, keeps syncing the rest, and still fails the sync
once more than half of the users or groups fail."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.google_drive import group_sync
from ee.onyx.external_permissions.models import SyncEntityFailure
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.db.enums import SyncEntityKind

_DRIVE_ID = "shared-drive"


def _folder(folder_id: str) -> dict[str, Any]:
    return {
        "id": folder_id,
        "permissions": [
            {"id": f"perm-{folder_id}", "type": "user", "emailAddress": "x@a.com"}
        ],
    }


def _member(email: str) -> MagicMock:
    member = MagicMock()
    member.email = email
    return member


@patch.object(group_sync, "get_modified_folders")
def test_failing_user_is_reported_and_the_others_sync(
    mock_get_modified_folders: MagicMock,
) -> None:
    def _folders(ops: Any, user_email: str) -> Iterator[dict[str, Any]]:  # noqa: ARG001
        if user_email == "b@a.com":
            raise RuntimeError("403 for b")
        yield _folder(f"folder-{user_email}")

    mock_get_modified_folders.side_effect = _folders
    connector = MagicMock()
    connector._get_all_user_emails.return_value = ["a@a.com", "b@a.com", "c@a.com"]

    items = list(
        group_sync._get_all_folders(
            google_drive_connector=connector, skip_folders_without_permissions=True
        )
    )

    assert [item.id for item in items] == [
        "folder-a@a.com",
        "b@a.com",
        "folder-c@a.com",
    ]
    failure = items[1]
    assert isinstance(failure, SyncEntityFailure)
    assert failure.kind == SyncEntityKind.USER
    assert failure.message == "403 for b"


def _run_gdrive_group_sync(
    groups: dict[str, list[str] | Exception],
) -> list[ExternalUserGroup | SyncEntityFailure]:
    """Runs the sync with one shared drive shared with every group."""

    def _list_group_members(group_email: str) -> Iterator[MagicMock]:
        members = groups[group_email]
        if isinstance(members, Exception):
            raise members
        yield from (_member(email) for email in members)

    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.list_group_members.side_effect = _list_group_members
    connector = MagicMock()
    connector.ops = ops
    cc_pair = MagicMock()
    with (
        patch.object(group_sync, "GoogleDriveConnector", return_value=connector),
        patch.object(group_sync, "build_connector_kwargs", return_value={}),
        patch.object(group_sync, "credential_json", return_value={}),
        patch.object(
            group_sync,
            "_get_drive_members",
            return_value={_DRIVE_ID: (set(groups), set())},
        ),
        patch.object(group_sync, "_get_all_google_groups", return_value=list(groups)),
        patch.object(group_sync, "_get_all_folders", return_value=iter([])),
        patch.object(group_sync, "_get_all_domain_users", return_value=[]),
    ):
        return list(group_sync.gdrive_group_sync("tenant", cc_pair))


def test_failing_google_group_is_skipped_whole_and_reported() -> None:
    items = _run_gdrive_group_sync(
        {
            "good@a.com": ["alice@a.com"],
            "bad@a.com": RuntimeError("members unreadable"),
            "other@a.com": ["carol@a.com"],
        }
    )

    failures = [item for item in items if isinstance(item, SyncEntityFailure)]
    assert len(failures) == 1
    assert failures[0].kind == SyncEntityKind.GROUP
    assert failures[0].id == "bad@a.com"
    assert failures[0].message == "members unreadable"

    groups = {
        item.id: set(item.user_emails)
        for item in items
        if isinstance(item, ExternalUserGroup)
    }
    assert "bad@a.com" not in groups
    assert groups["good@a.com"] == {"alice@a.com"}
    # The drive grants the failed group too, but only the readable members land.
    assert groups[_DRIVE_ID] == {"alice@a.com", "carol@a.com"}


def test_too_many_failed_google_groups_fail_the_sync() -> None:
    with pytest.raises(RuntimeError, match="Too many failed group member fetches"):
        _run_gdrive_group_sync(
            {
                "a@a.com": RuntimeError("down"),
                "b@a.com": RuntimeError("down"),
                "c@a.com": ["carol@a.com"],
            }
        )
