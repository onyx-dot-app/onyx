from __future__ import annotations

from collections import deque
from collections.abc import Generator
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
from typing import Any

import pytest

from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector import DriveItemData
from onyx.connectors.sharepoint.connector import SHARED_DOCUMENTS_MAP
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SharepointConnectorCheckpoint
from onyx.connectors.sharepoint.connector import SiteDescriptor


class _FakeQuery:
    def __init__(self, payload: Sequence[Any]) -> None:
        self._payload = payload

    def execute_query(self) -> Sequence[Any]:
        return self._payload


class _FakeDrive:
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = f"fake-drive-id-{name}"
        self.web_url = f"https://example.sharepoint.com/sites/sample/{name}"


class _FakeDrivesCollection:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get(self) -> _FakeQuery:
        return _FakeQuery(list(self._drives))


class _FakeSite:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.drives = _FakeDrivesCollection(drives)


class _FakeSites:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get_by_url(self, _url: str) -> _FakeSite:
        return _FakeSite(self._drives)


class _FakeGraphClient:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.sites = _FakeSites(drives)


_SAMPLE_ITEM = DriveItemData(
    id="item-1",
    name="sample.pdf",
    web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
    parent_reference_path=None,
    drive_id="fake-drive-id",
)


def _build_connector(drives: Sequence[_FakeDrive]) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = _FakeGraphClient(drives)
    return connector


def _fake_iter_drive_items_paged(
    self: SharepointConnector,  # noqa: ARG001
    drive_id: str,  # noqa: ARG001
    folder_path: str | None = None,  # noqa: ARG001
    start: datetime | None = None,  # noqa: ARG001
    end: datetime | None = None,  # noqa: ARG001
    page_size: int = 200,  # noqa: ARG001
) -> Generator[DriveItemData, None, None]:
    yield _SAMPLE_ITEM


def _fake_iter_drive_items_delta(
    self: SharepointConnector,  # noqa: ARG001
    drive_id: str,  # noqa: ARG001
    start: datetime | None = None,  # noqa: ARG001
    end: datetime | None = None,  # noqa: ARG001
    page_size: int = 200,  # noqa: ARG001
) -> Generator[DriveItemData, None, None]:
    yield _SAMPLE_ITEM


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_fetch_driveitems_matches_international_drive_names(
    requested_drive_name: str,
    graph_drive_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector([_FakeDrive(graph_drive_name)])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    monkeypatch.setattr(
        SharepointConnector,
        "_iter_drive_items_delta",
        _fake_iter_drive_items_delta,
    )

    results = list(connector._fetch_driveitems(site_descriptor=site_descriptor))

    assert len(results) == 1
    drive_item, returned_drive_name, drive_web_url = results[0]
    assert drive_item.id == _SAMPLE_ITEM.id
    assert returned_drive_name == requested_drive_name
    assert drive_web_url is not None


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_get_drive_items_for_drive_id_matches_map(
    requested_drive_name: str,
    graph_drive_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector([_FakeDrive(graph_drive_name)])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    monkeypatch.setattr(
        SharepointConnector,
        "_iter_drive_items_delta",
        _fake_iter_drive_items_delta,
    )

    items_iter = connector._get_drive_items_for_drive_id(
        site_descriptor=site_descriptor,
        drive_id="fake-drive-id",
    )

    results = list(items_iter)
    assert len(results) == 1
    assert results[0].id == _SAMPLE_ITEM.id


def test_load_from_checkpoint_maps_drive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = SharepointConnector()
    connector._graph_client = object()
    connector.include_site_pages = False

    captured_drive_names: list[str] = []
    sample_item = DriveItemData(
        id="doc-1",
        name="sample.pdf",
        web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
        parent_reference_path=None,
        drive_id="fake-drive-id",
    )

    def fake_resolve_drive(
        self: SharepointConnector,  # noqa: ARG001
        site_descriptor: SiteDescriptor,  # noqa: ARG001
        drive_name: str,
    ) -> tuple[str, str | None]:
        assert drive_name == "Documents"
        return (
            "fake-drive-id",
            "https://example.sharepoint.com/sites/sample/Documents",
        )

    def fake_fetch_one_delta_page(
        self: SharepointConnector,  # noqa: ARG001
        page_url: str,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> tuple[list[DriveItemData], str | None]:
        return [sample_item], None

    def fake_convert(
        driveitem: DriveItemData,  # noqa: ARG001
        drive_name: str,
        ctx: Any,  # noqa: ARG001
        graph_client: Any,  # noqa: ARG001
        graph_api_base: str,  # noqa: ARG001
        include_permissions: bool,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
        access_token: str | None = None,  # noqa: ARG001
    ) -> Document:
        captured_drive_names.append(drive_name)
        return Document(
            id="doc-1",
            source=DocumentSource.SHAREPOINT,
            semantic_identifier="sample.pdf",
            metadata={},
            sections=[TextSection(link="https://example.com", text="content")],
        )

    def fake_get_access_token(self: SharepointConnector) -> str:  # noqa: ARG001
        return "fake-access-token"

    monkeypatch.setattr(
        SharepointConnector,
        "_resolve_drive",
        fake_resolve_drive,
    )
    monkeypatch.setattr(
        SharepointConnector,
        "_fetch_one_delta_page",
        fake_fetch_one_delta_page,
    )
    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_driveitem_to_document_with_permissions",
        fake_convert,
    )
    monkeypatch.setattr(
        SharepointConnector,
        "_get_graph_access_token",
        fake_get_access_token,
    )

    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque()
    checkpoint.current_site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=SHARED_DOCUMENTS_MAP["Documents"],
        folder_path=None,
    )
    checkpoint.cached_drive_names = deque(["Documents"])
    checkpoint.current_drive_name = None
    checkpoint.process_site_pages = False

    generator = connector._load_from_checkpoint(
        start=0,
        end=0,
        checkpoint=checkpoint,
        include_permissions=False,
    )

    all_yielded: list[Any] = []
    try:
        while True:
            all_yielded.append(next(generator))
    except StopIteration:
        pass

    from onyx.connectors.models import HierarchyNode

    documents = [item for item in all_yielded if not isinstance(item, HierarchyNode)]
    hierarchy_nodes = [item for item in all_yielded if isinstance(item, HierarchyNode)]

    assert len(documents) == 1
    assert captured_drive_names == [SHARED_DOCUMENTS_MAP["Documents"]]
    assert len(hierarchy_nodes) >= 1


def test_get_drive_items_uses_delta_when_no_folder_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is None, _get_drive_items_for_drive_id should use delta."""
    connector = _build_connector([_FakeDrive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path=None,
    )

    called_method: list[str] = []

    def fake_delta(
        self: SharepointConnector,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("delta")
        yield _SAMPLE_ITEM

    def fake_paged(
        self: SharepointConnector,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        folder_path: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(SharepointConnector, "_iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(SharepointConnector, "_iter_drive_items_paged", fake_paged)

    items = connector._get_drive_items_for_drive_id(site, "fake-drive-id")
    list(items)

    assert called_method == ["delta"]


def test_get_drive_items_uses_paged_when_folder_path_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is set, _get_drive_items_for_drive_id should use BFS."""
    connector = _build_connector([_FakeDrive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path="Engineering/Docs",
    )

    called_method: list[str] = []

    def fake_delta(
        self: SharepointConnector,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("delta")
        yield _SAMPLE_ITEM

    def fake_paged(
        self: SharepointConnector,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        folder_path: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(SharepointConnector, "_iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(SharepointConnector, "_iter_drive_items_paged", fake_paged)

    items = connector._get_drive_items_for_drive_id(site, "fake-drive-id")
    list(items)

    assert called_method == ["paged"]


def test_iter_drive_items_delta_uses_timestamp_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delta iteration should pass the start time as a URL token for incremental sync."""
    connector = SharepointConnector()

    captured_urls: list[str] = []

    def fake_graph_api_get_json(
        self: SharepointConnector,  # noqa: ARG001
        url: str,
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        captured_urls.append(url)
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

    monkeypatch.setattr(
        SharepointConnector, "_graph_api_get_json", fake_graph_api_get_json
    )

    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    items = list(connector._iter_drive_items_delta("d1", start=start))

    assert len(items) == 1
    assert items[0].id == "file-1"
    assert len(captured_urls) == 1
    assert "token=2025-06-01T00%3A00%3A00%2B00%3A00" in captured_urls[0]


def test_iter_drive_items_delta_full_crawl_when_no_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delta iteration without a start time should do a full enumeration (no token)."""
    connector = SharepointConnector()

    captured_urls: list[str] = []

    def fake_graph_api_get_json(
        self: SharepointConnector,  # noqa: ARG001
        url: str,
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        captured_urls.append(url)
        return {
            "value": [],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d1/root/delta?token=final",
        }

    monkeypatch.setattr(
        SharepointConnector, "_graph_api_get_json", fake_graph_api_get_json
    )

    list(connector._iter_drive_items_delta("d1"))

    assert len(captured_urls) == 1
    assert "token=" not in captured_urls[0]
    assert captured_urls[0].endswith("/drives/d1/root/delta")


def test_iter_drive_items_delta_skips_folders_and_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delta results with folder or deleted facets should be skipped."""
    connector = SharepointConnector()

    def fake_graph_api_get_json(
        self: SharepointConnector,  # noqa: ARG001
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

    monkeypatch.setattr(
        SharepointConnector, "_graph_api_get_json", fake_graph_api_get_json
    )

    items = list(connector._iter_drive_items_delta("d1"))
    assert len(items) == 1
    assert items[0].id == "file-1"


def test_iter_drive_items_delta_handles_410_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On 410 Gone, delta should fall back to full enumeration."""
    import requests as req

    connector = SharepointConnector()

    call_count = 0

    def fake_graph_api_get_json(
        self: SharepointConnector,  # noqa: ARG001
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

    monkeypatch.setattr(
        SharepointConnector, "_graph_api_get_json", fake_graph_api_get_json
    )

    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    items = list(connector._iter_drive_items_delta("d1", start=start))

    assert len(items) == 1
    assert items[0].id == "file-1"
    assert call_count == 2
