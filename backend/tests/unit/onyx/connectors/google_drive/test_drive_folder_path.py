"""`build_folder_path` reads each folder as the next user when a read
fails, and caches only a full read."""

from collections.abc import Iterator
from typing import Any, cast

import pytest

from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.doc_conversion import build_folder_path
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)

_DRIVE_ID = "drive-1"
_FOLDER_ID = "folder-1"
_FILE: dict[str, Any] = {
    "id": "file-1",
    "name": "Plan",
    "driveId": _DRIVE_ID,
    "parents": [_FOLDER_ID],
}
_MEMBER = "member@example.com"
# Got the folder by a share: sees the folder, not its parent or the drive.
_SHAREE = "sharee@example.com"
# Sees nothing in the drive.
_OUTSIDER = "outsider@example.com"
_FULL_PATH = ["Team Drive", "Hiring"]


class _FakeOps:
    def get_file(
        self,
        *,
        user_email: str,
        file_id: str,
        fields: str,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        if file_id == _DRIVE_ID and user_email == _MEMBER:
            return {"name": "Drive"}
        if file_id != _FOLDER_ID:
            return None
        if user_email == _MEMBER:
            return {"name": "Hiring", "parents": [_DRIVE_ID]}
        if user_email == _SHAREE:
            return {"name": "Hiring"}
        return None

    def get_shared_drive_name(self, *, user_email: str, drive_id: str) -> str | None:
        assert drive_id == _DRIVE_ID
        return "Team Drive" if user_email == _MEMBER else None


@pytest.fixture(autouse=True)
def clear_folder_cache() -> Iterator[None]:
    doc_conversion._folder_cache.clear()
    yield
    doc_conversion._folder_cache.clear()


def _ops() -> GoogleDriveSourceOperations:
    return cast(GoogleDriveSourceOperations, _FakeOps())


@pytest.mark.parametrize("first_user", [_OUTSIDER, _SHAREE])
def test_a_failed_folder_read_does_not_set_the_path_of_later_files(
    first_user: str,
) -> None:
    """A user who cannot read the folder, or cannot see its parent, gets a
    short path. A later read as a drive member gets the full path."""
    ops = _ops()
    assert build_folder_path(_FILE, ops, first_user) != _FULL_PATH

    assert build_folder_path(_FILE, ops, _MEMBER) == _FULL_PATH


def test_a_failed_folder_read_tries_the_next_user() -> None:
    ops = _ops()
    path = build_folder_path(_FILE, ops, _OUTSIDER, path_readers=[_SHAREE, _MEMBER])
    assert path == _FULL_PATH
