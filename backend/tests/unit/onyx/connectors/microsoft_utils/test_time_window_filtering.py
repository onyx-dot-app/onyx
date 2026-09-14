"""[start, end] filtering of drive items in the shared Graph package.

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

from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemData,
    fetch_one_delta_page,
    iter_delta_pages,
    iter_drive_items_paged,
    parse_graph_datetime,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "fake-drive-id"

# The incremental window: "everything that changed since the last run".
START = datetime(2026, 3, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 2, tzinfo=timezone.utc)


def _item(item_id: str, created: str | None, modified: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": item_id,
        "name": f"{item_id}.pdf",
        "webUrl": f"https://example.sharepoint.com/{item_id}.pdf",
        "file": {"mimeType": "application/pdf"},
        "parentReference": {"driveId": DRIVE_ID, "path": "/drives/d1/root:"},
    }
    if created is not None:
        item["createdDateTime"] = created
    if modified is not None:
        item["lastModifiedDateTime"] = modified
    return item


# A file synced in during the window, carrying its original (much older)
# modification date from the user's local filesystem.
SYNCED_IN_ITEM = _item("synced-in", "2026-03-01T10:00:00Z", "2025-11-14T08:30:00Z")

# A file that predates the window on both timestamps.
UNCHANGED_ITEM = _item("unchanged", "2025-01-05T09:00:00Z", "2025-02-06T09:00:00Z")

# A file created in the window and modified after it closed.
STRADDLING_ITEM = _item("straddling", "2026-03-01T12:00:00Z", "2026-03-03T09:00:00Z")

# A file that landed after the window closed.
AFTER_WINDOW_ITEM = _item(
    "after-window", "2026-03-05T10:00:00Z", "2026-03-05T10:00:00Z"
)

# Files whose latest change sits exactly on a bound.
AT_START_ITEM = _item("at-start", "2026-03-01T00:00:00Z", "2025-12-01T00:00:00Z")
AT_END_ITEM = _item("at-end", "2026-02-01T00:00:00Z", "2026-03-02T00:00:00Z")

# A file Graph returned without either timestamp.
NO_TIMESTAMPS_ITEM = _item("no-timestamps", None, None)

ALL_ITEMS = [
    SYNCED_IN_ITEM,
    UNCHANGED_ITEM,
    STRADDLING_ITEM,
    AFTER_WINDOW_ITEM,
    AT_START_ITEM,
    AT_END_ITEM,
    NO_TIMESTAMPS_ITEM,
]

Window = tuple[datetime | None, datetime | None]
Collector = Callable[[GraphApiClient, Window], list[str]]


class _FakeGraphClient(GraphApiClient):
    """A Graph client whose every call returns a canned payload."""

    def __init__(self, get_json: Callable[..., dict[str, Any]]) -> None:
        super().__init__(lambda: "fake-token", GRAPH_API_BASE)
        self._fake_get_json = get_json

    def get_json(
        self, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return self._fake_get_json(url, params)


def _client(payload: dict[str, Any]) -> GraphApiClient:
    return _FakeGraphClient(lambda _url, _params=None: payload)


def _paged_ids(client: GraphApiClient, window: Window) -> list[str]:
    start, end = window
    return [
        item.id
        for item in iter_drive_items_paged(
            client, drive_id=DRIVE_ID, start=start, end=end
        )
    ]


def _delta_pages_ids(client: GraphApiClient, window: Window) -> list[str]:
    start, end = window
    return [
        item.id
        for item in iter_delta_pages(
            client,
            initial_url=f"{GRAPH_API_BASE}/drives/{DRIVE_ID}/root/delta",
            drive_id=DRIVE_ID,
            start=start,
            end=end,
            page_size=200,
            allow_full_resync=False,
        )
    ]


def _one_delta_page_ids(client: GraphApiClient, window: Window) -> list[str]:
    start, end = window
    items, _ = fetch_one_delta_page(
        client,
        page_url=f"{GRAPH_API_BASE}/drives/{DRIVE_ID}/root/delta",
        drive_id=DRIVE_ID,
        start=start,
        end=end,
    )
    return [item.id for item in items]


# Each item source applies the same window filter, so they get the same cases.
ITEM_SOURCES = [
    pytest.param(_paged_ids, id="iter_drive_items_paged"),
    pytest.param(_delta_pages_ids, id="iter_delta_pages"),
    pytest.param(_one_delta_page_ids, id="fetch_one_delta_page"),
]

# (window, ids expected out of ALL_ITEMS). Order follows ALL_ITEMS.
WINDOW_CASES = [
    pytest.param(
        (START, END),
        ["synced-in", "at-start", "at-end", "no-timestamps"],
        id="bounded",
    ),
    pytest.param(
        (START, None),
        [
            "synced-in",
            "straddling",
            "after-window",
            "at-start",
            "at-end",
            "no-timestamps",
        ],
        id="start_only",
    ),
    pytest.param(
        (None, END),
        ["synced-in", "unchanged", "at-start", "at-end", "no-timestamps"],
        id="end_only",
    ),
    pytest.param(
        (None, None),
        [item["id"] for item in ALL_ITEMS],
        id="no_window",
    ),
]


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
@pytest.mark.parametrize("window,expected_ids", WINDOW_CASES)
def test_window_filter_matches_contract(
    collect_ids: Collector,
    window: Window,
    expected_ids: list[str],
) -> None:
    """Bounds are inclusive, either bound may be absent, items with no timestamp
    stay, and the later of the two timestamps places an item."""
    client = _client({"value": ALL_ITEMS})

    assert collect_ids(client, window) == expected_ids


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
def test_file_synced_in_during_window_is_returned(
    collect_ids: Collector,
) -> None:
    """A file added during the window counts as new even when its
    lastModifiedDateTime was back-dated by the sync client."""
    client = _client({"value": [SYNCED_IN_ITEM]})

    assert collect_ids(client, (START, END)) == ["synced-in"]


@pytest.mark.parametrize("collect_ids", ITEM_SOURCES)
def test_file_modified_after_window_waits_for_the_next_window(
    collect_ids: Collector,
) -> None:
    """Only the latest change places an item, so a file created in this window
    but modified after it belongs to the next poll window."""
    client = _client({"value": [STRADDLING_ITEM]})

    assert collect_ids(client, (START, END)) == []


def test_created_datetime_is_parsed_onto_drive_item_data() -> None:
    """The filter relies on createdDateTime surviving the JSON parse."""
    item = DriveItemData.from_graph_json(SYNCED_IN_ITEM)

    assert item.created_datetime == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    assert item.last_modified_datetime == datetime(
        2025, 11, 14, 8, 30, tzinfo=timezone.utc
    )


def test_parse_graph_datetime_returns_aware_utc() -> None:
    """The window bounds are aware UTC, so parsed values must be too."""
    expected = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)

    assert parse_graph_datetime("2026-03-01T10:00:00Z") == expected
    assert parse_graph_datetime("2026-03-01T10:00:00") == expected
    assert parse_graph_datetime("2026-03-01T12:00:00+02:00") == expected
    assert parse_graph_datetime(datetime(2026, 3, 1, 10, 0)) == expected
    assert parse_graph_datetime(None) is None
    with pytest.raises(TypeError):
        parse_graph_datetime(1772359200)  # ty: ignore[invalid-argument-type]
