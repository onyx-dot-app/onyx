from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.sharepoint.connector import (
    SharepointConnector,
    SiteDrive,
    _build_driveitem_metadata,
)


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


def _delta_item(
    item_id: str, name: str, parent_id: str | None, path: str | None = None
) -> DriveItemData:
    return DriveItemData(
        id=item_id,
        name=name,
        web_url="https://x/" + name,
        parent_id=parent_id,
        parent_reference_path=path,
    )


def test_delta_items_get_folder_path_from_parent_lookup() -> None:
    folders = {
        "f1": _delta_item("f1", "R&D Plans", "root", "/drives/d/root:/Eng"),
        "f2": _delta_item("f2", "Top", "root", "/drives/d/root:"),
        "root": _delta_item("root", "root", None),
    }
    ops = MagicMock()
    ops.get_drive_item.side_effect = lambda drive_id, item_id: (  # noqa: ARG005
        folders[item_id]
    )
    connector = SharepointConnector()
    connector._ops = ops

    items = [
        _delta_item("a", "a.docx", "f1"),
        _delta_item("b", "b.docx", "f1"),
        _delta_item("c", "c.docx", "f2"),
        _delta_item("d", "d.docx", "root"),
        _delta_item("e", "e.docx", "f1", "/drives/d/root:/Kept"),
    ]
    out = list(connector._resolve_delta_item_paths("d", items))

    assert out[0].parent_reference_path == "/drives/d/root:/Eng/R%26D%20Plans"
    assert out[1].parent_reference_path == out[0].parent_reference_path
    assert out[2].parent_reference_path == "/drives/d/root:/Top"
    assert out[3].parent_reference_path is None
    assert out[4].parent_reference_path == "/drives/d/root:/Kept"
    assert ops.get_drive_item.call_count == 3


def test_failed_parent_lookup_keeps_item_and_skips_parent_for_the_run() -> None:
    ops = MagicMock()
    ops.get_drive_item.side_effect = MicrosoftGraphError(500, "boom", "x")
    connector = SharepointConnector()
    connector._ops = ops

    items = [_delta_item("a", "a.docx", "f1"), _delta_item("b", "b.docx", "f1")]
    out = list(connector._resolve_delta_item_paths("d", items))

    assert [i.id for i in out] == ["a", "b"]
    assert all(i.parent_reference_path is None for i in out)
    assert ops.get_drive_item.call_count == 1


def test_failed_parent_lookup_raises_when_excluded_paths_are_set() -> None:
    ops = MagicMock()
    ops.get_drive_item.side_effect = MicrosoftGraphError(500, "boom", "x")
    connector = SharepointConnector(excluded_paths=["Engineering/*"])
    connector._ops = ops

    with pytest.raises(MicrosoftGraphError):
        list(connector._resolve_delta_item_paths("d", [_delta_item("a", "a", "f1")]))


def test_throttled_parent_lookup_propagates() -> None:
    error = MicrosoftGraphError(429, "tooManyRequests", "slow down")
    ops = MagicMock()
    ops.get_drive_item.side_effect = error
    connector = SharepointConnector()
    connector._ops = ops

    with pytest.raises(MicrosoftGraphError):
        list(connector._resolve_delta_item_paths("d", [_delta_item("a", "a", "f1")]))
