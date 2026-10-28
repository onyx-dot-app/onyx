from __future__ import annotations

import pytest

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.sharepoint.connector import SiteDrive, _build_driveitem_metadata


def _drive() -> SiteDrive:
    return SiteDrive(
        drive_id="drive-id",
        display_name="Documents",
        web_url="https://contoso.sharepoint.com/sites/eng/Shared%20Documents",
    )


def _item(parent_reference_path: str | None) -> DriveItemData:
    return DriveItemData(
        id="item-id",
        name="report.docx",
        web_url="https://contoso.sharepoint.com/sites/eng/report.docx",
        parent_reference_path=parent_reference_path,
    )


@pytest.mark.parametrize(
    ("parent_reference_path", "expected"),
    [
        (
            "/drives/drive-id/root:/Engineering/API",
            {"drive": "Documents", "path": "Engineering/API"},
        ),
        (
            "/drives/drive-id/root:/Engineering",
            {"drive": "Documents", "path": "Engineering"},
        ),
        # percent-encoded segments are decoded
        (
            "/drives/drive-id/root:/R%26D%20Plans/Q1%202026",
            {"drive": "Documents", "path": "R&D Plans/Q1 2026"},
        ),
        # item at the root of the library: no path key
        ("/drives/drive-id/root:", {"drive": "Documents"}),
        ("/drives/drive-id/root:/", {"drive": "Documents"}),
        # parentReference.path missing
        (None, {"drive": "Documents"}),
        ("", {"drive": "Documents"}),
    ],
)
def test_build_driveitem_metadata(
    parent_reference_path: str | None, expected: dict[str, str]
) -> None:
    assert _build_driveitem_metadata(_item(parent_reference_path), _drive()) == expected
