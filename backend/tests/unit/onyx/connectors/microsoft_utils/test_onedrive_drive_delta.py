"""Drive delta pages preserve Graph change metadata and safe checkpoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

from onyx.connectors.microsoft_utils.drive_delta import (
    GRAPH_SHARED_CHANGED_PROPERTY,
    ODATA_DELTA_LINK_PROPERTY,
    ODATA_NEXT_LINK_PROPERTY,
    DriveDeltaPage,
    build_onedrive_delta_request_headers,
    fetch_drive_delta_checkpoint_page,
)
from onyx.connectors.microsoft_utils.drive_items import fetch_one_delta_page
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "drive-id"
DELTA_URL = f"{GRAPH_API_BASE}/drives/{DRIVE_ID}/root/delta"


class _FakeGraphClient(GraphApiClient):
    def __init__(self, get_json: Callable[..., dict[str, Any]]) -> None:
        super().__init__(lambda: "fake-token", GRAPH_API_BASE)
        self._get_json = get_json

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._get_json(url, params, headers)


def _gone(location: str | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 410
    if location:
        response.headers["Location"] = location
    return requests.HTTPError(response=response)


def test_drive_delta_page_parses_items_annotations_and_links() -> None:
    next_link = f"{DELTA_URL}?token=next"
    delta_link = f"{DELTA_URL}?token=complete"
    page = DriveDeltaPage.model_validate(
        {
            "value": [
                {
                    "id": "file",
                    "name": "report.docx",
                    "file": {"mimeType": "application/docx"},
                    "shared": {
                        "scope": "users",
                        "sharedDateTime": "2026-09-15T12:00:00Z",
                    },
                    GRAPH_SHARED_CHANGED_PROPERTY: True,
                },
                {"id": "folder", "folder": {"childCount": 2}},
                {"id": "deleted", "deleted": {"state": "deleted"}},
                {"id": "removed", "@removed": {"reason": "changed"}},
            ],
            ODATA_NEXT_LINK_PROPERTY: next_link,
            ODATA_DELTA_LINK_PROPERTY: delta_link,
        }
    )

    assert [item.id for item in page.items] == [
        "file",
        "folder",
        "deleted",
        "removed",
    ]
    assert page.items[0].file is not None
    assert page.items[0].is_file
    assert page.items[0].shared is not None
    assert page.items[0].shared.scope == "users"
    assert page.items[0].shared_changed is True
    assert page.items[1].is_folder
    assert page.items[2].is_tombstone
    assert page.items[3].is_tombstone
    assert page.next_link == next_link
    assert page.delta_link == delta_link


def test_checkpoint_fetch_keeps_next_link_and_prefer_headers() -> None:
    next_link = f"{DELTA_URL}?token=next"
    captured: list[tuple[str, dict[str, str] | None, dict[str, str] | None]] = []

    def get_json(
        url: str,
        params: dict[str, str] | None,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        captured.append((url, params, headers))
        return {
            "value": [{"id": "folder", "folder": {"childCount": 0}}],
            ODATA_NEXT_LINK_PROPERTY: next_link,
        }

    headers = build_onedrive_delta_request_headers()
    result = fetch_drive_delta_checkpoint_page(
        _FakeGraphClient(get_json),
        page_url=DELTA_URL,
        drive_id=DRIVE_ID,
        request_headers=headers,
    )

    assert [item.id for item in result.page.items] == ["folder"]
    assert result.next_checkpoint_url == next_link
    assert result.resync_after_410 is False
    assert captured == [(DELTA_URL, None, headers)]


def test_410_keeps_trusted_server_resync_location() -> None:
    supplied_url = f"{DELTA_URL}?$deltatoken=server-resync"

    def get_json(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise _gone(supplied_url)

    result = fetch_drive_delta_checkpoint_page(
        _FakeGraphClient(get_json),
        page_url=f"{DELTA_URL}?token=expired",
        drive_id=DRIVE_ID,
    )

    assert result.page.items == []
    assert result.next_checkpoint_url == supplied_url
    assert result.resync_after_410 is True


def test_410_rejects_untrusted_resync_location() -> None:
    def get_json(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise _gone("https://attacker.example/root/delta?token=stolen")

    result = fetch_drive_delta_checkpoint_page(
        _FakeGraphClient(get_json),
        page_url=f"{DELTA_URL}?token=expired",
        drive_id=DRIVE_ID,
    )

    assert result.next_checkpoint_url is not None
    assert result.next_checkpoint_url.startswith(f"{DELTA_URL}?$top=200&$select=")
    assert "token=" not in result.next_checkpoint_url


def test_sharepoint_file_wrapper_keeps_filtering_and_file_only_result() -> None:
    payload = {
        "value": [
            {
                "id": "old-file",
                "name": "old.pdf",
                "webUrl": "https://example.sharepoint.com/old.pdf",
                "file": {"mimeType": "application/pdf"},
                "lastModifiedDateTime": "2025-01-01T00:00:00Z",
            },
            {
                "id": "current-file",
                "name": "current.pdf",
                "webUrl": "https://example.sharepoint.com/current.pdf",
                "file": {"mimeType": "application/pdf"},
                "lastModifiedDateTime": "2026-09-15T12:00:00Z",
            },
            {"id": "folder", "folder": {"childCount": 0}},
            {"id": "deleted", "deleted": {"state": "deleted"}},
            {"id": "removed", "@removed": {"reason": "changed"}},
        ]
    }
    client = _FakeGraphClient(lambda *_args: payload)

    delta_result = fetch_drive_delta_checkpoint_page(
        client,
        page_url=DELTA_URL,
        drive_id=DRIVE_ID,
    )
    files, next_url = fetch_one_delta_page(
        client,
        page_url=DELTA_URL,
        drive_id=DRIVE_ID,
        start=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert len(delta_result.page.items) == 5
    assert [item.id for item in files] == ["current-file"]
    assert next_url is None
