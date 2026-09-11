"""Delta-walk behaviour of the shared Graph drive-item helpers.

Covers the incremental token, the full enumeration when there is no start time,
the folder/deleted facets that must be skipped, and the 410 Gone resync.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from onyx.connectors.microsoft_utils.drive_items import (
    DRIVE_ITEM_DOWNLOAD_URL_SELECT,
    DRIVE_ITEM_SELECT_FIELDS,
    iter_drive_items_delta,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class _FakeGraphClient(GraphApiClient):
    """A Graph client whose every call returns a canned payload."""

    def __init__(self, get_json: Callable[..., dict[str, Any]]) -> None:
        super().__init__(lambda: "fake-token", GRAPH_API_BASE)
        self._fake_get_json = get_json

    def get_json(
        self, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return self._fake_get_json(url, params)


def test_iter_drive_items_delta_uses_timestamp_token() -> None:
    """Delta iteration should pass the start time as a URL token for incremental sync."""

    captured_urls: list[str] = []
    captured_params: list[dict[str, str] | None] = []

    def fake_graph_api_get_json(
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        captured_urls.append(url)
        captured_params.append(params)
        return {
            "value": [
                {
                    "id": "file-1",
                    "name": "report.docx",
                    "webUrl": "https://example.sharepoint.com/report.docx",
                    "file": {
                        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    },
                    "lastModifiedDateTime": "2025-06-15T12:00:00Z",
                    "parentReference": {"path": "/drives/d1/root:", "driveId": "d1"},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d1/root/delta?token=final",
        }

    client = _FakeGraphClient(fake_graph_api_get_json)

    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    items = list(iter_drive_items_delta(client, "d1", start=start))

    assert len(items) == 1
    assert items[0].id == "file-1"
    assert len(captured_urls) == 1
    assert "token=2025-06-01T00%3A00%3A00%2B00%3A00" in captured_urls[0]
    assert captured_params == [{"$top": "200", "$select": DRIVE_ITEM_SELECT_FIELDS}]
    assert DRIVE_ITEM_DOWNLOAD_URL_SELECT in DRIVE_ITEM_SELECT_FIELDS.split(",")


def test_iter_drive_items_delta_full_crawl_when_no_start() -> None:
    """Delta iteration without a start time should do a full enumeration (no token)."""

    captured_urls: list[str] = []

    def fake_graph_api_get_json(
        url: str,
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        captured_urls.append(url)
        return {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d1/root/delta?token=final",
        }

    client = _FakeGraphClient(fake_graph_api_get_json)

    list(iter_drive_items_delta(client, "d1"))

    assert len(captured_urls) == 1
    assert "token=" not in captured_urls[0]
    assert captured_urls[0].endswith("/drives/d1/root/delta")


def test_iter_drive_items_delta_skips_folders_and_deleted() -> None:
    """Delta results with folder or deleted facets should be skipped."""

    def fake_graph_api_get_json(
        url: str,  # noqa: ARG001
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        return {
            "value": [
                {"id": "folder-1", "name": "Docs", "folder": {"childCount": 5}},
                {"id": "deleted-1", "name": "old.txt", "deleted": {"state": "deleted"}},
                {
                    "id": "file-1",
                    "name": "keep.pdf",
                    "webUrl": "https://example.sharepoint.com/keep.pdf",
                    "file": {"mimeType": "application/pdf"},
                    "lastModifiedDateTime": "2025-06-15T12:00:00Z",
                    "parentReference": {"path": "/drives/d1/root:", "driveId": "d1"},
                },
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d1/root/delta?token=final",
        }

    client = _FakeGraphClient(fake_graph_api_get_json)

    items = list(iter_drive_items_delta(client, "d1"))
    assert len(items) == 1
    assert items[0].id == "file-1"


def test_iter_drive_items_delta_handles_410_gone() -> None:
    """On 410 Gone, delta should fall back to full enumeration."""
    import requests as req

    call_count = 0

    def fake_graph_api_get_json(
        url: str,
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1

        if call_count == 1 and "token=" in url:
            response = req.Response()
            response.status_code = 410
            raise req.HTTPError(response=response)

        return {
            "value": [
                {
                    "id": "file-1",
                    "name": "doc.pdf",
                    "webUrl": "https://example.sharepoint.com/doc.pdf",
                    "file": {"mimeType": "application/pdf"},
                    "lastModifiedDateTime": "2025-06-15T12:00:00Z",
                    "parentReference": {"path": "/drives/d1/root:", "driveId": "d1"},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d1/root/delta?token=final",
        }

    client = _FakeGraphClient(fake_graph_api_get_json)

    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    items = list(iter_drive_items_delta(client, "d1", start=start))

    assert len(items) == 1
    assert items[0].id == "file-1"
    assert call_count == 2
