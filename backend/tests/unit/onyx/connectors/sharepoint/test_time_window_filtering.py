"""[start, end] filtering of drive items in the SharePoint connector.

Graph preserves a file's original ``lastModifiedDateTime`` when it is copied or
synced in, setting only ``createdDateTime`` to the arrival time, so filtering on
modification alone strands those files until a full re-index. Covers all three
item sources: BFS children, streaming delta, and per-page delta.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.connectors.sharepoint.connector import (
    GRAPH_API_BASE,
    DriveItemData,
    SharepointConnector,
)

DRIVE_ID = "fake-drive-id"

# The incremental window: "everything that changed since the last run".
START = datetime(2026, 3, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 2, tzinfo=timezone.utc)

# A file synced in during the window, carrying its original (much older)
# modification date from the user's local filesystem.
SYNCED_IN_ITEM = {
    "id": "synced-in",
    "name": "old_report.pdf",
    "webUrl": "https://example.sharepoint.com/old_report.pdf",
    "file": {"mimeType": "application/pdf"},
    "createdDateTime": "2026-03-01T10:00:00Z",
    "lastModifiedDateTime": "2025-11-14T08:30:00Z",
    "parentReference": {"driveId": DRIVE_ID, "path": "/drives/d1/root:"},
}

# A file that predates the window on both timestamps.
UNCHANGED_ITEM = {
    "id": "unchanged",
    "name": "ancient.pdf",
    "webUrl": "https://example.sharepoint.com/ancient.pdf",
    "file": {"mimeType": "application/pdf"},
    "createdDateTime": "2025-01-05T09:00:00Z",
    "lastModifiedDateTime": "2025-02-06T09:00:00Z",
    "parentReference": {"driveId": DRIVE_ID, "path": "/drives/d1/root:"},
}

# A file that landed after the window closed.
AFTER_WINDOW_ITEM = {
    "id": "after-window",
    "name": "future.pdf",
    "webUrl": "https://example.sharepoint.com/future.pdf",
    "file": {"mimeType": "application/pdf"},
    "createdDateTime": "2026-03-05T10:00:00Z",
    "lastModifiedDateTime": "2026-03-05T10:00:00Z",
    "parentReference": {"driveId": DRIVE_ID, "path": "/drives/d1/root:"},
}


def _connector(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> SharepointConnector:
    """A connector whose Graph calls always return ``payload``."""
    connector = SharepointConnector()

    def fake_get_json(
        self: SharepointConnector,  # noqa: ARG001
        url: str,  # noqa: ARG001
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(SharepointConnector, "_graph_api_get_json", fake_get_json)
    return connector


def _paged_ids(connector: SharepointConnector) -> list[str]:
    return [
        item.id
        for item in connector._iter_drive_items_paged(
            drive_id=DRIVE_ID, start=START, end=END
        )
    ]


def _delta_pages_ids(connector: SharepointConnector) -> list[str]:
    return [
        item.id
        for item in connector._iter_delta_pages(
            initial_url=f"{GRAPH_API_BASE}/drives/{DRIVE_ID}/root/delta",
            drive_id=DRIVE_ID,
            start=START,
            end=END,
            page_size=200,
            allow_full_resync=False,
        )
    ]


def _one_delta_page_ids(connector: SharepointConnector) -> list[str]:
    items, _ = connector._fetch_one_delta_page(
        page_url=f"{GRAPH_API_BASE}/drives/{DRIVE_ID}/root/delta",
        drive_id=DRIVE_ID,
        start=START,
        end=END,
    )
    return [item.id for item in items]


# Each item source applies the same window filter, so they get the same cases.
ITEM_SOURCES = [
    pytest.param(_paged_ids, id="iter_drive_items_paged"),
    pytest.param(_delta_pages_ids, id="iter_delta_pages"),
    pytest.param(_one_delta_page_ids, id="fetch_one_delta_page"),
]


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
def test_file_synced_in_during_window_is_returned(
    monkeypatch: pytest.MonkeyPatch,
    collect_ids: Callable[[SharepointConnector], list[str]],
) -> None:
    """A file added during the window counts as new even when its
    lastModifiedDateTime was back-dated by the sync client."""
    connector = _connector(monkeypatch, {"value": [SYNCED_IN_ITEM]})

    assert collect_ids(connector) == ["synced-in"]


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
def test_file_untouched_before_window_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    collect_ids: Callable[[SharepointConnector], list[str]],
) -> None:
    """Items whose createdDateTime and lastModifiedDateTime both predate the
    window stay out."""
    connector = _connector(monkeypatch, {"value": [UNCHANGED_ITEM]})

    assert collect_ids(connector) == []


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
def test_file_added_after_window_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    collect_ids: Callable[[SharepointConnector], list[str]],
) -> None:
    connector = _connector(monkeypatch, {"value": [AFTER_WINDOW_ITEM]})

    assert collect_ids(connector) == []


def test_created_datetime_is_parsed_onto_drive_item_data() -> None:
    """The filter relies on createdDateTime surviving the JSON parse."""
    item = DriveItemData.from_graph_json(SYNCED_IN_ITEM)

    assert item.created_datetime == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    assert item.last_modified_datetime == datetime(
        2025, 11, 14, 8, 30, tzinfo=timezone.utc
    )
