from __future__ import annotations

from collections import deque
from collections.abc import Generator
from collections.abc import Sequence
from datetime import datetime
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
        "_iter_drive_items_paged",
        _fake_iter_drive_items_paged,
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
        "_iter_drive_items_paged",
        _fake_iter_drive_items_paged,
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

    def fake_get_drive_items(
        self: SharepointConnector,  # noqa: ARG001
        site_descriptor: SiteDescriptor,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None,  # noqa: ARG001
        end: datetime | None,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        yield sample_item

    def fake_convert(
        driveitem: DriveItemData,  # noqa: ARG001
        drive_name: str,
        ctx: Any,  # noqa: ARG001
        graph_client: Any,  # noqa: ARG001
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
        "_get_drive_items_for_drive_id",
        fake_get_drive_items,
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
