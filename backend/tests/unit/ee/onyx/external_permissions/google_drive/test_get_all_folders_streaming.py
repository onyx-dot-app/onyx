import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.google_drive.group_sync import _get_all_folders


def _folder(folder_id: str) -> dict[str, Any]:
    """A Drive folder payload carrying one non-inherited permission.

    No "permissionDetails" means inherited_from is None, so the permission
    survives the inherited-permission filter and the folder is kept.
    """
    permission_id = f"perm-{folder_id}"
    return {
        "id": folder_id,
        "name": folder_id,
        "permissionIds": [permission_id],
        "permissions": [
            {
                "id": permission_id,
                "type": "user",
                "emailAddress": f"{folder_id}@example.com",
            }
        ],
    }


def _make_connector(user_emails: list[str]) -> MagicMock:
    connector = MagicMock()
    connector.creds = MagicMock()
    connector._get_all_user_emails.return_value = user_emails
    return connector


@patch("ee.onyx.external_permissions.google_drive.group_sync.get_modified_folders")
@patch("ee.onyx.external_permissions.google_drive.group_sync.get_drive_service")
def test_get_all_folders_streams_without_materializing(
    mock_get_drive_service: MagicMock,
    mock_get_modified_folders: MagicMock,
) -> None:
    """Folders must be yielded as they are found, not accumulated into a list.

    Building the full list before returning is what pinned the entire
    folder/permission graph in memory and OOM-killed the heavy worker. This
    asserts the generator emits its first folder after touching only the first
    user, so a regression back to list-building fails here.
    """
    assert inspect.isgeneratorfunction(_get_all_folders)

    mock_get_drive_service.return_value = MagicMock()
    mock_get_modified_folders.side_effect = [
        [_folder("a1"), _folder("a2")],
        [_folder("b1")],
        [_folder("c1")],
    ]
    connector = _make_connector(["a@example.com", "b@example.com", "c@example.com"])

    generator = _get_all_folders(
        google_drive_connector=connector, skip_folders_without_permissions=True
    )

    # Merely calling the function must not perform any work.
    assert mock_get_drive_service.call_count == 0

    first = next(generator)

    # One folder pulled => only the first user has been enumerated.
    assert first.id == "a1"
    assert mock_get_drive_service.call_count == 1

    # Draining the rest reaches the remaining users.
    remaining = [folder.id for folder in generator]
    assert remaining == ["a2", "b1", "c1"]
    assert mock_get_drive_service.call_count == 3


@patch("ee.onyx.external_permissions.google_drive.group_sync.get_modified_folders")
@patch("ee.onyx.external_permissions.google_drive.group_sync.get_drive_service")
def test_get_all_folders_dedupes_across_users(
    mock_get_drive_service: MagicMock,
    mock_get_modified_folders: MagicMock,
) -> None:
    """Every user re-enumerates the whole domain, so the shared seen-set must
    still collapse duplicates now that folders are streamed rather than
    appended to a shared list."""
    mock_get_drive_service.return_value = MagicMock()
    mock_get_modified_folders.side_effect = [
        [_folder("shared"), _folder("only-a")],
        [_folder("shared"), _folder("only-b")],
    ]
    connector = _make_connector(["a@example.com", "b@example.com"])

    folder_ids = [
        folder.id
        for folder in _get_all_folders(
            google_drive_connector=connector, skip_folders_without_permissions=True
        )
    ]

    assert folder_ids == ["shared", "only-a", "only-b"]


@patch("ee.onyx.external_permissions.google_drive.group_sync.get_modified_folders")
@patch("ee.onyx.external_permissions.google_drive.group_sync.get_drive_service")
def test_get_all_folders_aborts_after_too_many_user_failures(
    mock_get_drive_service: MagicMock,
    mock_get_modified_folders: MagicMock,
) -> None:
    """Failure accounting must still abort mid-stream. With yield from, the
    per-user exception surfaces when the consumer pulls, so the guard has to
    keep working from inside the generator."""
    mock_get_drive_service.return_value = MagicMock()
    mock_get_modified_folders.side_effect = RuntimeError("drive unavailable")
    connector = _make_connector([f"u{i}@example.com" for i in range(4)])

    with pytest.raises(RuntimeError, match="Too many failed folder fetches"):
        list(
            _get_all_folders(
                google_drive_connector=connector,
                skip_folders_without_permissions=True,
            )
        )
